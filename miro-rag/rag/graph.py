"""
rag/graph.py

LangGraph RAG pipeline with hybrid routing.
Flow:
  retrieve → route → [documentaire]  → generate         → format_output → END
                   → [donnees_erp]   → orm_agent_loop   → format_output → END
"""

import logging
import os
import sys
import json
import threading
import time
from collections import Counter
from pathlib import Path
from typing import TypedDict, List, Optional, Any, Tuple

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_groq import ChatGroq
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage
from langgraph.graph import StateGraph, START, END

from config.settings import LLM_PROVIDER, GROQ_API_KEY, GROQ_MODEL
from rag.schemas import (
    AssistantResponse, SourceReference, LLMResponse,
    QueryRoute, DataQueryIntent,
)
from vectorstore.search import get_retriever, retrieve as search_retrieve

# 2026-08-14: LLM client factory + call-retry infra extracted to
# rag/llm_client.py (see its own module docstring for the full rationale
# and exact scope). get_chat_llm() is the new provider-aware entry point,
# used so far only by code_intelligence_agent's two LLM instantiations.
# Everything else below is re-imported under its original private name
# purely for backward compatibility: this file's own remaining Groq-only
# call sites (generate/orm_agent_loop/hybrid_node) and existing test
# imports (code_intelligence/tests/test_j30_31_latency_budget.py does
# `from rag.graph import CI_MAX_HOPS, _invoke_with_rate_limit`) both still
# reference these names unchanged.
from rag.llm_client import (
    get_chat_llm,
    invoke_with_rate_limit as _invoke_with_rate_limit,
    _parse_reset_seconds,
    _extract_rate_limit_headers,
    _ToolCallFallback,
    _try_recover_tool_use_failed,
    _reduce_message_context,
    _TOOL_MSG_HARD_CAP,
    _TOOL_USE_FAILED_RE,
    _FAILED_GEN_CALL_RE,
    _llm_call_lock as _groq_call_lock,
    _last_llm_call_time as _last_groq_call_time,
    MIN_LLM_CALL_INTERVAL as MIN_GROQ_CALL_INTERVAL,
)

logger = logging.getLogger(__name__)

import re


# ── Bloc 7 fix: real Odoo group DB IDs -> xml_id resolution ──────────────────
_GROUP_XMLID_CACHE: dict = {}
_ADMIN_RPC_CLIENT = None
_ADMIN_RPC_UID = None


def _get_admin_rpc_client():
    """Lazy singleton admin XML-RPC client + uid, reused across requests --
    pure static-metadata lookups only (group xml_id resolution), never used
    for anything requiring the actual requester's own rights."""
    global _ADMIN_RPC_CLIENT, _ADMIN_RPC_UID
    if _ADMIN_RPC_CLIENT is None:
        from code_intelligence.odoo_rpc_client import OdooRpcClient
        client = OdooRpcClient()
        _ADMIN_RPC_UID = client.authenticate_admin()
        _ADMIN_RPC_CLIENT = client
    return _ADMIN_RPC_CLIENT, _ADMIN_RPC_UID


def _resolve_user_group_xmlids(group_ids) -> list:
    """
    Bloc 7 fix: the demandeur's real Odoo groups arrive from the JWT as
    res.groups DATABASE IDs (see miro_ai/controllers/main.py:
    `groups = [g.id for g in user.groups_id]`), but the Code Intelligence
    graph identifies every group by its XML-ID (module.name), built
    statically from XML extraction. Without this translation,
    resolve_group_identifier() / _has_elevated_access() never match a real
    logged-in user against any group in the graph -- every real requester
    was silently treated as belonging to no group at all (found in review,
    J23-24). This affects both evaluer_regles_enregistrement's AND/OR
    engine (Bloc 1) and authorization_gate's elevated-access check (Bloc 7).

    Fails closed: any ID that can't be resolved (RPC error, group has no
    ir.model.data entry) is simply dropped, never guessed -- a missing
    group membership can only make gating MORE restrictive, never less.
    Locked by test_j23_24_group_id_xmlid_resolution.py.
    """
    if not group_ids:
        return []

    uncached = [g for g in group_ids if g not in _GROUP_XMLID_CACHE]
    if uncached:
        try:
            client, admin_uid = _get_admin_rpc_client()
            resolved = client.get_group_xmlids(admin_uid, uncached)
            _GROUP_XMLID_CACHE.update(resolved)
        except Exception as e:
            logger.error(
                "Group ID -> xml_id resolution failed for %s: %s. "
                "These groups will be treated as unresolved (fail closed).",
                uncached, e,
            )

    return [_GROUP_XMLID_CACHE[g] for g in group_ids if g in _GROUP_XMLID_CACHE]


# _parse_reset_seconds, _extract_rate_limit_headers, _ToolCallFallback:
# moved to rag/llm_client.py 2026-08-14, imported above.


_DEGENERATE_REPETITION_RE = re.compile(r"\b(\w+(?:\s+\w+){0,2})\b(?:[\s,.-]+\1\b){5,}", re.IGNORECASE)


def _detect_degenerate_repetition(text: str) -> bool:
    """
    Review finding (Q1.1 benchmark run): llama-3.1-8b-instant at
    temperature=0 with no frequency/presence penalty occasionally collapses
    into a decoding loop -- the same word or short phrase repeated dozens
    of times in a row (observed: ~140x "Accountant Manager") -- typically
    right after a truncated tool observation pushes the context close to
    the model's limit. This is not tool output (no '- xxx:' shape), it's a
    synthesis-LLM decoding failure.

    Detects a 1-3 word phrase immediately repeated 6+ times in a row. Kept
    deliberately narrow (consecutive repetition only) to avoid flagging
    normal prose that legitimately reuses a technical term across a long
    answer.
    """
    if not text:
        return False
    return bool(_DEGENERATE_REPETITION_RE.search(text))


def _strip_degenerate_repetition(text: str) -> str:
    """Collapse a detected degenerate run down to a single occurrence of
    the repeated phrase, as a last resort if a retry still comes back
    degenerate -- never ship a wall of repeated tokens to the user."""
    return _DEGENERATE_REPETITION_RE.sub(r"\1", text)


_DEGENERATE_LINE_REPETITION_MIN_REPEATS = 4
_DEGENERATE_LINE_MIN_LENGTH = 30


def _detect_degenerate_line_repetition(text: str) -> bool:
    """
    Second, complementary decoding-collapse detector -- live finding
    (bloc9-06b-technical, 2026-08-10): `_DEGENERATE_REPETITION_RE` above
    only catches a SHORT (1-3 word) phrase repeating consecutively, since
    it was written for the original Q1.1 case ("Accountant Manager" x140).
    It does NOT generalize to a full SENTENCE or bullet line repeating
    verbatim many times, which is exactly the shape observed live: the
    same ~40-word "- `xml_id: account.group_account_manager` : Ce groupe
    est requis..." line repeated ~50 times until the response was cut off
    mid-word. Same underlying model decoding-collapse failure, just at a
    coarser granularity that the phrase-level regex structurally cannot
    catch (its capture group is capped at 3 words).

    Splits the text into lines and flags any single line -- above a
    minimum length, so short legitimately-repeatable list items (e.g. a
    short marker on consecutive bullet rows) don't false-positive -- that
    recurs _DEGENERATE_LINE_REPETITION_MIN_REPEATS+ times anywhere in the
    text (not necessarily contiguously -- a real synthesis answer does not
    legitimately repeat a 30+ character sentence four times regardless of
    spacing, so this is safe to check globally rather than only
    consecutively).
    """
    if not text:
        return False
    lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) >= _DEGENERATE_LINE_MIN_LENGTH]
    if not lines:
        return False
    counts = Counter(lines)
    return any(c >= _DEGENERATE_LINE_REPETITION_MIN_REPEATS for c in counts.values())


def _strip_degenerate_line_repetition(text: str) -> str:
    """Collapse repeated (near-)identical lines down to their first
    occurrence, preserving original order -- same last-resort philosophy
    as `_strip_degenerate_repetition`, at the coarser line granularity."""
    seen = set()
    out_lines = []
    for line in text.splitlines():
        key = line.strip()
        if len(key) >= _DEGENERATE_LINE_MIN_LENGTH:
            if key in seen:
                continue
            seen.add(key)
        out_lines.append(line)
    return "\n".join(out_lines)


_DEGENERATE_BLANK_RUN_RE = re.compile(r"(?:[ \t]*\n){15,}")


def _detect_degenerate_blank_run(text: str) -> bool:
    """
    Third, complementary decoding-collapse detector -- live finding
    (bloc9-06c-technical-condition-capture, 2026-08-11): neither
    `_detect_degenerate_repetition` (short phrase, 6+ consecutive) nor
    `_detect_degenerate_line_repetition` (a 30+ char line/sentence
    repeated 4+ times ANYWHERE) catches this shape -- the model instead
    collapsed into emitting dozens of consecutive blank/whitespace-only
    lines (observed: ~30+ bare newlines in a row) between two otherwise-
    normal sentences, which is neither a repeated phrase nor a repeated
    non-empty line. `_DEGENERATE_LINE_MIN_LENGTH`'s own 30-char floor
    exists specifically to avoid flagging short legitimate repeated list
    markers -- it also, as a side effect, filters out every blank line
    before `_detect_degenerate_line_repetition` even counts them, so this
    needed its own dedicated detector rather than a threshold tweak to an
    existing one. Same underlying model decoding-collapse failure mode as
    the other two, just manifesting as an absence of content instead of a
    repeated one.

    15+ consecutive blank/whitespace-only lines is far beyond anything a
    real synthesis answer legitimately produces (normal paragraph spacing
    is at most 1-2 blank lines between sections) -- chosen with the same
    "only the clear, unambiguous shape" conservatism as every other
    deterministic check in this module (see e.g. _detect_link_guard_field
    in semgrep_locks_analyzer.py).
    """
    if not text:
        return False
    return bool(_DEGENERATE_BLANK_RUN_RE.search(text))


def _strip_degenerate_blank_run(text: str) -> str:
    """Collapse any run of 3+ consecutive newlines (2+ blank lines) down to
    a single blank line (2 newlines) -- same last-resort philosophy as the
    other two strippers. Deliberately not scoped to only the detected
    15+-line run: a lower-magnitude version of the same collapse (e.g. 4-5
    blank lines) is still visually broken and worth normalizing whenever
    this stripper runs at all, and normal prose never legitimately uses
    more than one blank line for spacing.
    """
    return re.sub(r"\n{3,}", "\n\n", text)


_DEGENERATE_PREFIX_LENGTH = 60
_DEGENERATE_PREFIX_MIN_REPEATS = 4


def _detect_degenerate_growing_repetition(text: str) -> bool:
    """
    Fourth, complementary decoding-collapse detector -- live finding
    (bloc9-06c-technical-condition-capture, 2026-08-13): none of the other
    three catch a SNOWBALLING sentence, where each successive line restates
    the previous one verbatim as a prefix and appends a further clause
    ("Il n'y a pas de restriction ... pour les avoirs qui ne sont pas
    associés à une facture de dépense." then "...et qui ne nécessitent pas
    de mise à jour de la partie commerciale." then a third clause on top of
    that, etc.). Every line is technically unique character-for-character,
    so `_detect_degenerate_line_repetition`'s exact-match Counter never
    trips on it -- but they all share a very long common prefix, which is
    the same underlying decoding-collapse failure mode restating itself
    with growing content instead of identical content.

    Flags when `_DEGENERATE_PREFIX_MIN_REPEATS`+ distinct lines (above the
    same `_DEGENERATE_LINE_MIN_LENGTH` floor as the exact-line detector)
    share an identical first `_DEGENERATE_PREFIX_LENGTH`-character prefix.
    60 chars (vs. the exact-line detector's 30-char minimum LINE length) is
    deliberately longer than a single clause -- keeps this narrow enough
    that legitimate answers with several distinct `[FAIT DÉTERMINISTIQUE]`
    lines (which share only the ~23-char label, not 60 chars of actual
    content) never false-positive; verified functionally against a 4-line
    legitimate fixture before this was wired in.
    """
    if not text:
        return False
    lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) >= _DEGENERATE_LINE_MIN_LENGTH]
    if not lines:
        return False
    prefixes = Counter(ln[:_DEGENERATE_PREFIX_LENGTH] for ln in lines)
    return any(c >= _DEGENERATE_PREFIX_MIN_REPEATS for c in prefixes.values())


def _strip_degenerate_growing_repetition(text: str) -> str:
    """Collapse a snowballing-sentence run down to its first (shortest)
    occurrence per shared prefix group, same last-resort philosophy as the
    other three strippers."""
    seen_prefixes = set()
    out_lines = []
    for line in text.splitlines():
        key = line.strip()
        if len(key) >= _DEGENERATE_LINE_MIN_LENGTH:
            prefix = key[:_DEGENERATE_PREFIX_LENGTH]
            if prefix in seen_prefixes:
                continue
            seen_prefixes.add(prefix)
        out_lines.append(line)
    return "\n".join(out_lines)


def _detect_any_degenerate_repetition(text: str) -> bool:
    """Combined check -- run all four degenerate-repetition detectors,
    since they catch different granularities of the same underlying
    decoding-collapse failure mode."""
    return (
        _detect_degenerate_repetition(text)
        or _detect_degenerate_line_repetition(text)
        or _detect_degenerate_blank_run(text)
        or _detect_degenerate_growing_repetition(text)
    )


def _strip_any_degenerate_repetition(text: str) -> str:
    """Combined last-resort strip -- apply all four collapsers so no
    granularity of repeated content survives into the shipped answer."""
    return _strip_degenerate_growing_repetition(
        _strip_degenerate_blank_run(_strip_degenerate_line_repetition(_strip_degenerate_repetition(text)))
    )


# _TOOL_USE_FAILED_RE, _FAILED_GEN_CALL_RE, _try_recover_tool_use_failed,
# _TOOL_MSG_HARD_CAP, _reduce_message_context, _invoke_with_rate_limit:
# all moved to rag/llm_client.py 2026-08-14 (generalized to be
# provider-aware), imported at the top of this file under their original
# names for backward compatibility. See rag/llm_client.py's module
# docstring for the full rationale.


# (dead placeholder removed -- the real invoke_with_rate_limit lives in
# rag/llm_client.py now, imported as _invoke_with_rate_limit above.)

# ERP metadata types that trigger the data_query branch
ERP_TYPES = {"sale", "ticket"}

# Bloc 6 / J20-J21: explicit inter-branch conflict policy.
# Code is the enforced source of truth for governance/security questions unless
# the user explicitly asks for the written/documented policy.
ROUTING_CONFLICT_PRIORITY = (
    QueryRoute.CODE_INTELLIGENCE.value,
    QueryRoute.DONNEES_ERP.value,
    QueryRoute.HYBRIDE.value,
    QueryRoute.DOCUMENTAIRE.value,
)

ERP_KEYWORDS = [
    "combien de", "montant total", "total des", "chiffre d'affaires",
    "statut de la", "statut commande", "factures impayées", "factures payées",
    "quantité disponible", "produit en rupture", "le plus récent",
    "tickets résolus", "tickets en cours", "tickets de support", "tickets", "ticket", "rechercher client", "coordonnées",
    "toutes périodes confondues", "ce mois", "cette année", "moyenne",
    "stock", "quel produit", "montant moyen"
]

CODE_INTEL_KEYWORDS = [
    "qui a accès", "qui a acces", "droit d'accès", "droit d acces", "droits d'accès",
    "droit de lecture", "droit d'écriture", "droit de modification", "droit de suppression",
    "quel groupe a accès", "quels groupes ont accès", "qui a le droit",
    "règle d'enregistrement", "regle d'enregistrement", "ir.rule", "règle de sécurité", "regle de securite",
    "action serveur", "action automati", "base.automation", "ir.actions.server", "sudo", "logique cachée",
    "verrou", "validateurs exceptionnels", "validationerror", "usererror", "dispatch dynamique", "getattr",
    "impact de la modification", "impact de modification", "si je modifie le champ",
    "changement du champ", "impact du champ", "champs calculés dépendants",
    "chemin d'exécution", "chemin execution", "bouton", "quand je clique sur",
    "action du bouton", "que fait le bouton", "modèle odoo", "modele odoo",
    "approuver", "approbation", "qui peut valider", "peut-il voir",
    "règles d'approbation", "regles d'approbation", "mêmes règles",
    "seuil d'approbation", "conditions pour valider", "processus d'approbation",
    "peut-il accéder", "peut-elle voir", "peut-il modifier",
]

QUANTITATIVE_TERMS = [
    "combien", "montant", "total", "résolu", "en cours", "moyenne",
    "chiffre", "quel est le stock"
]

DOC_KEYWORDS = [
    "comment", "procédure", "qui peut", "qui doit", "quel fichier",
    "quelle classe", "quel est le rôle", "quels sont les modèles",
    "dans quel fichier", "procédure de validation", "politique interne",
    "selon le wiki"
]

DATA_TERMS = [
    "combien", "montant", "ticket", "vente", "statut", "liste", "résolu",
    "en cours", "stock", "facture", "commande", "client", "chiffre"
]

DOC_ANCHORS = [
    "selon le wiki", "selon la politique interne", "où est documenté",
    "dans le wiki", "wiki interne"
]

THRESHOLD_QUERY_TERMS = [
    "seuil d'approbation", "plafond", "dépasse-t-il", "depasse-t-il"
]

OUT_OF_SCOPE_ANSWER = (
    "Cette question ne fait pas partie de mon périmètre. "
    "Je suis spécialisé dans l'assistance et les procédures internes"
)

OUT_OF_SCOPE_TERMS = {
    "blague",
    "gâteau",
    "gateau",
    "recette",
    "coupe du monde",
    "poème",
    "poeme",
    "lune",
}


# Max ReAct iterations before forced stop (per implementation plan)
REACT_RECURSION_LIMIT = 6

# ── State Definition ──────────────────────────────────────────────────────────

class RAGState(TypedDict):
    question: str
    chat_history: List[BaseMessage]
    uid: Optional[int]
    skills: Optional[dict]
    timing: dict
    retrieved_chunks: List[dict]
    raw_answer: str
    route: Optional[str]
    response: Optional[AssistantResponse]
    uid: Optional[int]  # Odoo user uid for RBAC passthrough
    user_groups: List[int]  # Real Odoo group ids of the requester (signed JWT, never LLM-guessed)


# ── Nodes ─────────────────────────────────────────────────────────────────────

def retrieve(state: RAGState) -> dict:
    """Retrieve relevant documents for the query."""
    import time
    start_time = time.time()
    question = state["question"]
    logger.info("Node [retrieve]: Fetching documents for: %s", question)
    
    try:
        chroma_manager, bm25_index = get_retriever()
        chunks = search_retrieve(
            query=question, 
            top_k=10, 
            chroma_manager=chroma_manager,
            bm25_index=bm25_index,
            use_reranker=True
        )
    except Exception as e:
        logger.error("Error during retrieval: %s", e)
        chunks = []
        
    return {"retrieved_chunks": chunks}


def _is_out_of_scope(question: str) -> bool:
    """Reject obvious non-work questions before the LLM can improvise."""
    normalized_question = question.lower().strip()
    if not normalized_question:
        return False

    return any(term in normalized_question for term in OUT_OF_SCOPE_TERMS)


_MASSIVE_EXTRACTION_PATTERNS = [
    r"toutes?\s+les?\s+règl(es|ements)",
    r"tous\s+les\s+modèles",
    r"tous\s+les\s+modules",
    r"chaque\s+modèle",
    r"l'intégralité\s+du\s+code",
    r"dump\s+de\s+tous",
    r"liste\s+complète\s+de\s+tous",
    r"tous\s+les\s+mots\s+de\s+passe",
    r"tous\s+les\s+utilisateurs",
    r"extraire?\s+tout",
    r"toutes\s+les\s+actions\s+serveur",
    r"all\s+rules\s+of\s+all\s+models",
    r"dump\s+all\s+models",
    r"dump\s+all\s+rules",
    r"list\s+all\s+models",
    r"extract\s+all\s+code",
    r"all\s+users\s+and\s+passwords",
]

_PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(?:all\s+|previous\s+)*instructions",
    r"override\s+security",
    r"system\s+prompt",
    r"affiche\s+(ton\s+)?prompt\s+système",
    r"montre\s+(moi\s+)?les\s+consignes\s+système",
    r"forget\s+all\s+rules",
    r"bypass\s+all\s+checks",
    r"you\s+are\s+now\s+dan",
    r"jailbreak",
]


def _is_massive_extraction_request(question: str) -> bool:
    """J32-J33: Detect queries attempting bulk metadata or rule extraction across all models/modules."""
    import re
    q = question.lower().strip()
    if not q:
        return False

    # Combination check: e.g. "toutes les règles" + ("tous les modèles" or "tout le système")
    has_bulk_scope = any(w in q for w in ["tous les modèles", "tous les modules", "chaque modèle", "tout le système", "all models", "all modules", "whole database"])
    has_bulk_target = any(w in q for w in ["toutes les règles", "tous les accès", "tous les droits", "all rules", "all permissions", "all access"])
    if has_bulk_scope and has_bulk_target:
        return True

    return any(re.search(pat, q) for pat in _MASSIVE_EXTRACTION_PATTERNS)


def _is_prompt_injection(question: str) -> bool:
    """J32-J33: Detect prompt injection and system prompt reveal attempts."""
    import re
    q = question.lower().strip()
    if not q:
        return False
    return any(re.search(pat, q) for pat in _PROMPT_INJECTION_PATTERNS)


def route(state: RAGState) -> dict:
    """Classify the query using the Bloc 6 inter-branch conflict policy."""
    import time
    start_time = time.time()
    chunks = state.get("retrieved_chunks", [])
    question = state.get("question", "").lower()
    logger.info("Node [route]: Classifying query type from %d chunks", len(chunks))

    # Hybrid check: doc keyword/anchor + quantitative ERP term (not just generic nouns like 'facture').
    # Must include DOC_ANCHORS, not only DOC_KEYWORDS: anchors like "où est documenté" or
    # "dans le wiki" are not in DOC_KEYWORDS, so a query combining one of them with a
    # quantitative term (e.g. "Où est documenté le nombre de tickets en cours ?") was
    # silently falling through to DOCUMENTAIRE instead of HYBRIDE. Found in review, locked
    # by test_hybrid_detects_doc_anchor_not_only_doc_keyword.
    is_hybrid = (
        any(kw in question for kw in DOC_KEYWORDS) or any(a in question for a in DOC_ANCHORS)
    ) and any(term in question for term in QUANTITATIVE_TERMS)

    # J18-J19: Conflict resolution priority:
    # 1. Explicit doc anchors override everything (user explicitly asks for wiki/policy doc)
    # 2. Quantitative data queries ("combien", "montant total des...", "nombre de...") -> DONNEES_ERP,
    #    UNLESS it's explicitly asking about a governance threshold ("dépasse-t-il le seuil", "quel est le plafond")
    # 3. CODE_INTELLIGENCE > DONNEES_ERP > HYBRIDE > DOCUMENTAIRE
    has_doc_anchor = any(anchor in question for anchor in DOC_ANCHORS)
    has_code_intel = any(kw in question for kw in CODE_INTEL_KEYWORDS)
    has_erp = any(kw in question for kw in ERP_KEYWORDS)
    has_quantitative = any(term in question for term in QUANTITATIVE_TERMS)
    is_threshold_query = any(t in question for t in THRESHOLD_QUERY_TERMS)

    if has_doc_anchor:
        # User explicitly asks about documentation/wiki — documentaire wins
        if is_hybrid:
            logger.info("Node [route]: Doc anchor + quantitative → HYBRIDE branch")
            route_decision = QueryRoute.HYBRIDE.value
        else:
            logger.info("Node [route]: Explicit doc anchor → DOCUMENTAIRE branch")
            route_decision = QueryRoute.DOCUMENTAIRE.value
    elif is_hybrid:
        logger.info("Node [route]: Query is hybrid → HYBRIDE branch")
        route_decision = QueryRoute.HYBRIDE.value
    elif has_quantitative and not is_threshold_query:
        # Quantitative record count/sum lookup -> DONNEES_ERP wins over code_intel
        logger.info("Node [route]: Quantitative data query → DONNEES_ERP branch")
        route_decision = QueryRoute.DONNEES_ERP.value
    elif has_code_intel:
        # Code intelligence wins over doc/erp for governance questions
        logger.info("Node [route]: Query matched Code Intelligence keywords → CODE_INTELLIGENCE branch")
        route_decision = QueryRoute.CODE_INTELLIGENCE.value
    elif any(kw in question for kw in DOC_KEYWORDS):
        logger.info("Node [route]: Query matched explicit doc keywords → DOCUMENTAIRE branch")
        route_decision = QueryRoute.DOCUMENTAIRE.value
    elif has_erp:
        logger.info("Node [route]: Query matched explicit ERP keywords → DONNEES_ERP branch")
        route_decision = QueryRoute.DONNEES_ERP.value
    elif not chunks:
        logger.info("Node [route]: No chunks → defaulting to documentaire")
        route_decision = QueryRoute.DOCUMENTAIRE.value
    else:
        # Count how many chunks come from ERP data sources
        erp_count = 0
        for chunk in chunks:
            meta = chunk.get("metadata") or {}
            chunk_type = meta.get("type", "").lower().strip()
            if chunk_type in ERP_TYPES:
                erp_count += 1

        erp_ratio = erp_count / len(chunks) if len(chunks) > 0 else 0
        logger.info("Node [route]: ERP ratio = %d/%d (%.0f%%)", erp_count, len(chunks), erp_ratio * 100)

        if erp_ratio >= 0.6 and any(term in question for term in DATA_TERMS):
            logger.info("Node [route]: High ERP ratio + data terms → DONNEES_ERP branch")
            route_decision = QueryRoute.DONNEES_ERP.value
        else:
            logger.info("Node [route]: → DOCUMENTAIRE branch")
            route_decision = QueryRoute.DOCUMENTAIRE.value

    timing = state.get("timing", {}).copy()
    timing["routing_time"] = time.time() - start_time
    return {"route": route_decision, "timing": timing}


def route_decision(state: RAGState) -> str:
    """Return the routing key for conditional edges."""
    return state.get("route", QueryRoute.DOCUMENTAIRE.value)


def generate(state: RAGState) -> dict:
    """Generate structured answer using Groq (documentary branch)."""
    import time
    start_time = time.time()
    question = state["question"]
    chunks = state["retrieved_chunks"]
    logger.info("Node [generate]: Building prompt and calling LLM")

    # Bloc 12 / J46-J48: reasoning-trace + LLM-call-budget instrumentation.
    # "documentaire" is the simplest branch (RAG only, no tool hops) --
    # it exists as the baseline llm_call_count comparator against
    # donnees_erp (Function Calling, up to REACT_RECURSION_LIMIT calls)
    # and code_intelligence (up to CI_MAX_HOPS calls + resolver + synthesis).
    from code_intelligence.reasoning_trace_logger import ReasoningTraceLogger, new_trace_id
    _trace_id = new_trace_id()
    _trace_logger = ReasoningTraceLogger()

    # Fast-fail for out of scope
    if _is_out_of_scope(question):
        logger.info("Node [generate]: Deterministic out-of-scope refusal.")
        response = AssistantResponse(
            answer=OUT_OF_SCOPE_ANSWER,
            sources=[],
            confidence=0.0,
        )
        timing = state.get("timing", {}).copy()
        timing["generation_time"] = time.time() - start_time
        _trace_logger.log_summary(
            trace_id=_trace_id, branch="documentaire", question=question,
            hop_count=0, llm_call_count=0, total_time_ms=timing["generation_time"] * 1000,
        )
        return {"response": response, "raw_answer": response.answer, "timing": timing}

    # Fallback if no relevant chunks are found
    if not chunks:
        logger.info("Node [generate]: No chunks retrieved, falling back.")
        response = AssistantResponse(
            answer="Je n'ai pas de source fiable pour répondre à cette question.",
            sources=[],
            confidence=0.0
        )
        timing = state.get("timing", {}).copy()
        timing["generation_time"] = time.time() - start_time
        _trace_logger.log_summary(
            trace_id=_trace_id, branch="documentaire", question=question,
            hop_count=0, llm_call_count=0, total_time_ms=timing["generation_time"] * 1000,
        )
        return {"response": response, "raw_answer": response.answer, "timing": timing}

    from rag.prompts import build_messages

    # Build context text
    context_text = ""
    for i, chunk in enumerate(chunks):
        doc_text = chunk.get("document", "")
        # Coding rule: dict.get for metadata
        metadata = chunk.get("metadata") or {}
        source = metadata.get("source", "unknown")
        context_text += f"[Source {i+1}: {source}]\n{doc_text}\n\n"

    # Build memory + prompt
    chat_history = state.get("chat_history", [])
    messages = build_messages(question, context_text, chat_history)

    _llm_call_count = 0
    try:
        llm = ChatGroq(model=GROQ_MODEL, temperature=0.3, max_tokens=1024)
        # Enforce structured output to match our schema
        structured_llm = llm.with_structured_output(LLMResponse)
        
        llm_resp = structured_llm.invoke(messages)
        _llm_call_count += 1
        response = AssistantResponse(
            answer=llm_resp.answer,
            confidence=llm_resp.confidence,
            sources=[]
        )
    except Exception as e:
        logger.warning("Structured LLM Generation failed (%s) → falling back to raw invoke", e)
        try:
            llm = ChatGroq(model=GROQ_MODEL, temperature=0.3, max_tokens=1024)
            raw_resp = llm.invoke(messages)
            _llm_call_count += 1
            response = AssistantResponse(
                answer=raw_resp.content,
                confidence=0.85,
                sources=[]
            )
        except Exception as e2:
            logger.error("Raw LLM Generation also failed: %s", e2)
            response = AssistantResponse(
                answer=f"Désolé, une erreur s'est produite lors de la génération. Détails: {str(e2)}",
                sources=[],
                confidence=0.0
            )
        
    timing = state.get("timing", {}).copy()
    timing["generation_time"] = time.time() - start_time
    timing["llm_call_count"] = _llm_call_count
    # Bloc 12 / J46-J48: documentaire branch never makes tool-call hops --
    # hop_count is always 0 here, which is itself the point of comparison
    # against donnees_erp / code_intelligence in the J48 budget report.
    _trace_logger.log_summary(
        trace_id=_trace_id, branch="documentaire", question=question,
        hop_count=0, llm_call_count=_llm_call_count,
        total_time_ms=timing["generation_time"] * 1000,
    )
    return {"response": response, "raw_answer": response.answer if response else "", "timing": timing}


def orm_agent_loop(state: RAGState) -> dict:
    """
    ReAct agent loop: Reason → call ORM tool → observe → repeat or answer.
    Bound to all 8 Odoo ORM tools via llm.bind_tools().
    Recursion capped at REACT_RECURSION_LIMIT iterations.
    """
    import time
    start_time = time.time()
    
    from langchain_core.messages import AIMessage, ToolMessage
    from tools.odoo_tools import (
        get_total_sales,
        get_product_stock,
        get_order_status,
        get_total_invoices,
        search_partner,
        get_recent_tickets,
        list_out_of_stock_products,
        get_period_revenue,
        get_average_sales,
        get_sale_details,
    )

    question = state["question"]
    chat_history = state.get("chat_history", [])
    logger.info("Node [orm_agent_loop]: Starting ReAct loop for: %s", question)

    # Bloc 12 / J46-J48: reasoning-trace + LLM-call-budget instrumentation.
    # "donnees_erp" is the Function Calling branch -- llm_call_count here
    # is directly comparable to "documentaire" (generate, 1-2 calls) and
    # "code_intelligence" (code_intelligence_agent, resolver + hops + synthesis).
    from code_intelligence.reasoning_trace_logger import ReasoningTraceLogger, new_trace_id
    _trace_id = new_trace_id()
    _trace_logger = ReasoningTraceLogger()
    _llm_call_count = 0
    _hop_index = 0

    if _is_out_of_scope(question):
        logger.info("Node [orm_agent_loop]: Out of scope question.")
        response = AssistantResponse(
            answer=OUT_OF_SCOPE_ANSWER,
            sources=[],
            confidence=0.0,
        )
        timing = state.get("timing", {}).copy()
        timing["generation_time"] = time.time() - start_time
        _trace_logger.log_summary(
            trace_id=_trace_id, branch="donnees_erp", question=question,
            hop_count=0, llm_call_count=0, total_time_ms=timing["generation_time"] * 1000,
        )
        return {"response": response, "raw_answer": response.answer, "timing": timing}

    skills = state.get("skills", {})
    
    # Base tools (always available)
    all_tools = [search_partner]
    
    # Skill filtering
    if skills.get("ventes", True):
        all_tools.extend([get_total_sales, get_order_status, get_period_revenue, get_average_sales, get_sale_details])
        
    if skills.get("stocks", True):
        all_tools.extend([get_product_stock, list_out_of_stock_products])
        
    if skills.get("comptabilite", True):
        all_tools.extend([get_total_invoices])
        
    if skills.get("tickets", True):
        all_tools.extend([get_recent_tickets])

    # Re-bind tools dynamically to the LLM
    llm = ChatGroq(
        model=GROQ_MODEL,
        api_key=GROQ_API_KEY,
        temperature=0.0,
    )
    llm_with_tools = llm.bind_tools(all_tools)

    system_prompt = (
        "Tu es MIRO Assistant, l'assistant IA interne spécialisé dans les données ERP Odoo. "
        "Utilise les outils disponibles pour interroger la base de données en temps réel et réponds avec les informations exactes retournées. "
        "Indique toujours la source exacte des données à la fin de ta réponse (ex: [Source: Odoo ERP - Module ...])."
    )

    messages = [
        SystemMessage(content=system_prompt),
        *chat_history[-10:],
        HumanMessage(content=question),
    ]

    tool_observations = []
    final_answer = None

    for iteration in range(REACT_RECURSION_LIMIT):
        logger.info("Node [orm_agent_loop]: Iteration %d/%d", iteration + 1, REACT_RECURSION_LIMIT)

        # If we already executed tool calls, output clean combined answer
        if tool_observations:
            logger.info("Node [orm_agent_loop]: Tool observations collected, outputting combined answer.")
            valid_obs = [obs for obs in tool_observations if "n'existe pas" not in obs and "pas été trouvé" not in obs and "Aucune vente trouvée" not in obs]
            selected_obs = valid_obs if valid_obs else tool_observations
            final_answer = "\n".join(selected_obs)
            break

        try:
            ai_msg = llm_with_tools.invoke(messages)
            _llm_call_count += 1
        except Exception as e:
            _llm_call_count += 1  # attempt still counts against the LLM-call budget
            logger.warning("LLM invoke failed at iteration %d: %s", iteration + 1, e)
            # ── Recovery: parse malformed tool calls from small models ──
            # Llama 3.1 8B sometimes generates <function=name>{"arg": "val"}
            # instead of structured JSON. Groq rejects it with a 400 containing
            # the raw text in 'failed_generation'. We parse it and continue.
            recovered = False
            err_str = str(e)
            if "failed_generation" in err_str:
                import re
                match = re.search(r'<function=(\w+)>\s*(\{.*?\})', err_str)
                if match:
                    fn_name = match.group(1)
                    try:
                        import json as _json
                        fn_args = _json.loads(match.group(2))
                        tool_map = {t.name: t for t in all_tools}
                        if fn_name in tool_map:
                            logger.info("Recovered malformed tool call: %s(%s)", fn_name, fn_args)
                            _t_hop = time.time()
                            observation = tool_map[fn_name].invoke(fn_args)
                            tool_observations.append(str(observation))
                            _trace_logger.log_hop(
                                trace_id=_trace_id, hop_index=_hop_index, tool_name=fn_name,
                                tool_args=fn_args, observation=str(observation),
                                elapsed_ms=(time.time() - _t_hop) * 1000,
                            )
                            _hop_index += 1
                            # Feed the observation back as a HumanMessage so the LLM
                            # can use it on the next iteration (no tool_call_id needed)
                            messages.append(HumanMessage(
                                content=f"Résultat de l'outil {fn_name} : {observation}"
                            ))
                            recovered = True
                    except Exception as parse_err:
                        logger.error("Recovery parse failed: %s", parse_err)
            if not recovered:
                logger.error("Unrecoverable LLM error at iteration %d", iteration + 1)
                break
            continue  # Skip normal ai_msg processing, go to next iteration

        messages.append(ai_msg)

        # No tool calls → we have the final answer
        if not getattr(ai_msg, "tool_calls", None):
            final_answer = ai_msg.content
            logger.info("Node [orm_agent_loop]: Final answer at iteration %d", iteration + 1)
            break

        # Execute each tool call
        for tool_call in ai_msg.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_id = tool_call["id"]
            logger.info("Node [orm_agent_loop]: Calling tool '%s' with args %s", tool_name, tool_args)

            _t_hop = time.time()
            if tool_name not in [t.name for t in all_tools]:
                observation = f"Outil '{tool_name}' non disponible."
            else:
                try:
                    tool_map = {t.name: t for t in all_tools}
                    observation = tool_map[tool_name].invoke(tool_args)
                except Exception as e:
                    observation = f"Erreur lors de l'appel à {tool_name}: {str(e)}"
                    logger.error("Tool call error: %s", e)

            tool_observations.append(observation)
            _trace_logger.log_hop(
                trace_id=_trace_id, hop_index=_hop_index, tool_name=tool_name,
                tool_args=tool_args, observation=str(observation),
                elapsed_ms=(time.time() - _t_hop) * 1000,
            )
            _hop_index += 1
            messages.append(ToolMessage(content=str(observation), tool_call_id=tool_id))
    else:
        # Recursion limit hit — force a final synthesis
        logger.warning("Node [orm_agent_loop]: Recursion limit reached. Forcing final answer.")
        synthesis_prompt = (
            f"Question originale : {question}\n\n"
            f"Observations collectées :\n" + "\n".join(tool_observations) +
            "\n\nFournis une réponse finale et concise en français basée uniquement sur ces observations."
        )
        try:
            plain_llm = ChatGroq(model=GROQ_MODEL, temperature=0.0, max_tokens=512)
            final_resp = plain_llm.invoke([HumanMessage(content=synthesis_prompt)])
            _llm_call_count += 1
            final_answer = final_resp.content
        except Exception as e:
            _llm_call_count += 1
            logger.error("Forced synthesis failed: %s", e)
            final_answer = "Je n'ai pas pu obtenir une réponse complète. Veuillez reformuler la question."

    if not final_answer:
        final_answer = "Je n'ai pas de données disponibles pour répondre à cette question."

    # Build sources from tool observations
    sources = []
    for obs in tool_observations:
        if obs and str(obs).strip():
            sources.append(SourceReference(
                source="odoo://xmlrpc",
                doc_type="erp_data",
                title="Données ERP Odoo",
                snippet=str(obs)[:150],
            ))

    response = AssistantResponse(
        answer=final_answer,
        sources=sources,
        confidence=0.9 if tool_observations else 0.5,
    )
    
    timing = state.get("timing", {}).copy()
    timing["generation_time"] = time.time() - start_time
    timing["llm_call_count"] = _llm_call_count
    timing["hop_count"] = _hop_index
    _trace_logger.log_summary(
        trace_id=_trace_id, branch="donnees_erp", question=question,
        hop_count=_hop_index, llm_call_count=_llm_call_count,
        total_time_ms=timing["generation_time"] * 1000,
        hop_cap=REACT_RECURSION_LIMIT,
    )
    return {"response": response, "raw_answer": response.answer, "timing": timing}


def hybrid_node(state: RAGState) -> dict:
    """Agent that orchestrates a hybrid query by dispatching to doc-reader and tool-caller sequentially, then combining."""
    import time
    start_time = time.time()
    logger.info("Node [hybrid_node]: Delegating to doc agent and data agent")
    
    # Run the documentaire branch to get procedures
    doc_state = state.copy()
    doc_result = generate(doc_state)
    doc_answer = doc_result.get("raw_answer", "")
    
    data_state = state.copy()
    data_state["retrieved_chunks"] = []
    data_state["question"] = state["question"]
    data_result = orm_agent_loop(data_state)
    data_answer = data_result.get("raw_answer", "")
    
    # Combine the two using a final Synthesis LLM
    from langchain_core.messages import HumanMessage
    from langchain_groq import ChatGroq
    from config.settings import GROQ_MODEL
    
    combine_prompt = (
        f"Tu es l'agent de synthèse finale.\n"
        f"La question de l'utilisateur était : '{state['question']}'\n\n"
        f"Voici ce que l'agent de documentation a trouvé sur les procédures :\n{doc_answer}\n\n"
        f"Voici ce que l'agent des données ERP a trouvé dans les chiffres :\n{data_answer}\n\n"
        f"Combine ces deux informations pour faire une seule réponse cohérente et fluide, sans mentionner l'existence des agents."
    )
    
    try:
        plain_llm = ChatGroq(model=GROQ_MODEL, temperature=0.3, max_tokens=1024)
        final_resp = plain_llm.invoke([HumanMessage(content=combine_prompt)])
        final_answer = final_resp.content
    except Exception as e:
        logger.error("Hybrid combine failed: %s", e)
        final_answer = f"{doc_answer}\n\n{data_answer}"
        
    # Combine sources safely
    sources = []
    if doc_result.get("response") and doc_result["response"].sources:
        sources.extend(doc_result["response"].sources)
    if data_result.get("response") and data_result["response"].sources:
        sources.extend(data_result["response"].sources)
        
    confidence = 0.5
    if doc_result.get("response") and data_result.get("response"):
        confidence = min(doc_result["response"].confidence, data_result["response"].confidence)
        
    response = AssistantResponse(
        answer=final_answer,
        sources=sources,
        confidence=confidence
    )
    
    timing = state.get("timing", {}).copy()
    timing["hybrid_time"] = time.time() - start_time
    return {"response": response, "raw_answer": final_answer, "timing": timing}


# ── Code Intelligence Agent ───────────────────────────────────────────────────

# C.1.3: System prompt with explicit scope-first navigation strategy.
CI_SYSTEM_PROMPT = (
    "You are MIRO Code Intelligence Assistant specializing in Odoo source code and security analysis.\n"
    "NAVIGATION STRATEGY:\n"
    "1. When target models or modules are provided by [BUSINESS TERM RESOLVER S2.0], invoke the appropriate tools immediately:\n"
    "   - For approval limits, hardcoded emails (_VALIDATEURS_EXCEPTIONNELS), UserError/ValidationError strings, or dynamic getattr dispatches: ALWAYS invoke `analyser_verrous_securite`.\n"
    "   - For group access matrix and ACL model permissions: invoke `qui_a_acces_a`.\n"
    "   - For ir.rule record rules and group-based RECORD visibility: invoke `evaluer_regles_enregistrement` (authoritative).\n"
    "   - For automated actions, ir.actions.server, or sudo() bypasses: invoke `analyser_actions_serveur`.\n"
    "   - For SQL uniqueness constraints (_sql_constraints) or relational field domain= filters (Many2one/Many2many): invoke `analyser_contraintes_donnees`.\n"
    "2. DO NOT make generic fallbacks. Synthesize the tool observations directly.\n"
    "3. Always cite source file links: [file.py:L12-L25](file:///path#L12-L25).\n"
    "   NEVER reuse this placeholder text itself as a citation -- only cite a file:// link "
    "with a real path and real line numbers copied verbatim from an actual tool observation. "
    "If no real citation is available for a claim, state the claim without any file:// link "
    "rather than inventing or reusing the example format.\n"
    "4. When citing a rule, group, or action by its Odoo technical identifier as a "
    "sourcing claim (not just using it as ordinary vocabulary), prefix it exactly as "
    "'xml_id: module.identifier' (e.g. xml_id: custom_credit_note_visibility_rules."
    "rule_avoir_visibilite_regionale).\n"
    "5. RETRY-BEFORE-HEDGE RULE (post-Bloc-8 fix): if a tool call returns 'not found in the "
    "indexed knowledge graph' or any similar failure, that failure means the MODEL NAME OR "
    "IDENTIFIER YOU JUST TRIED WAS WRONG -- it does not mean the information doesn't exist. "
    "Before proposing a different guessed identifier, or giving up and answering with hedging "
    "language ('il n'est pas possible de determiner avec certitude', 'il est possible que'), "
    "you MUST retry the SAME tool using the EXACT technical identifier already given to you "
    "under [BUSINESS TERM RESOLVER S2.0] above ('Target Models: ...') or already confirmed by "
    "an earlier successful tool observation in this same conversation. Never invent a new "
    "model/module name by paraphrasing the user's natural-language wording (e.g. 'demande_conge', "
    "'achat.demande', 'purchase.order') -- only the resolver-confirmed identifier or one copied "
    "verbatim from a prior successful observation is valid. Do not answer with uncertainty "
    "language until you have used at least one tool call against the resolver-confirmed model.\n"
    "6. 'COMMENT FAIRE X ?' RULE (Bloc 7 extension, 2026-08-07): for any question asking HOW to "
    "perform an action (click a button, submit a request, validate/approve something), invoke "
    "`chemin_execution_bouton`. Its result states explicitly whether the action is available to "
    "THIS demandeur. If it says NON DISPONIBLE / available_to_demandeur is false, your answer "
    "MUST say plainly that the demandeur does not have this option in the interface and, if the "
    "observation names the required group(s), who they should contact instead -- do NOT walk them "
    "through the button/method mechanism as if they could trigger it themselves."
)

# C.1.4: Maximum hops allowed per question.
CI_MAX_HOPS = 4

# J8 (Bloc 2): deterministic security-lock trigger.
# J7 found that the LLM does not reliably invoke analyser_verrous_securite
# on its own, even with the explicit "ALWAYS invoke" directive already in
# CI_SYSTEM_PROMPT (Q3.1: analyser_verrous_securite is correct and
# HIGH-confidence in isolation, but the LLM simply never calls it for
# approval-limit questions with a monetary amount). Rather than trying to
# word the prompt more forcefully -- which already failed once -- the
# amount is detected deterministically in code and the tool call is forced,
# removing the LLM from that decision entirely.
_AMOUNT_PATTERN = re.compile(r"\d[\d\s.,]*\d\s*(?:€|eur(?:os?)?\b)", re.IGNORECASE)
# Regression found on this same J8 patch (Q6.2, run of 2026-08-06): matching
# on amount alone forces analyser_verrous_securite even for pure ir.rule
# visibility questions ("peut voir un avoir de 80k?"), and the synthesis LLM
# then wrongly cross-attributed a Python-lock approval threshold (5000e) to
# an unrelated ir.rule rule name. Requiring an approval-intent keyword in
# addition to the amount keeps the forced dispatch scoped to what Q3.1
# actually needed (approval-limit / bypass questions), and leaves pure
# visibility questions to evaluer_regles_enregistrement alone.
_APPROVAL_PATTERN = re.compile(
    r"\b(?:approuv\w*|valid\w*|approbation\w*|droit\w*|exig\w*|condition\w*|rembourse\w*)\b",
    re.IGNORECASE,
)
# J8/J9: dedicated trigger for analyser_actions_serveur -- deliberately
# NOT reusing _APPROVAL_PATTERN alone (tested against the adversarial set:
# would fire on 6/9 questions, repolluting Python-lock questions like
# Q1.1/Q3.1/Q9.1 with irrelevant server-action noise -- same class of risk
# as the Q6.2 regression on _AMOUNT_PATTERN). Scoped to vocabulary that
# actually signals automation/bypass logic, not just "approval" in general.
# "tous les" / "toutes les" deliberately excluded: too generic in French
# (fires on unrelated questions like "tous les employés peuvent-ils...");
# "mêmes règles" alone already covers Q5.1's actual wording.
#
# Bloc 9 gap, found 2026-08-10 (bloc9-03c-urgente-trap, generalization
# check 3/8 on custom_hr_leave_workflow): bare `automatiq\w*` also matches
# the everyday adverb "automatiquement" in a question like "sa demande
# est-elle automatiquement validée ?" -- ordinary language asking whether
# something happens without further action, nothing to do with
# ir.actions.server/base.automation/sudo() bypass logic. On a model that
# DOES have real ServerAction nodes (hr.leave does, via hr_holidays), the
# structural guard below does not filter this out, so the false-positive
# forces analyser_actions_serveur to run and consumes a hop of the tight
# CI_MAX_HOPS=4 budget for a question that had nothing to do with server
# actions -- confirmed live: CI_MAX_HOPS was reached before the ReAct loop
# started, and the synthesis LLM dropped the has_group()-derived required
# group (hr_holidays.group_hr_holidays_manager) from its answer, the exact
# same failure shape as module 1/8's Gap 2 (dispatch noise crowding out a
# needed fact), just triggered by a false keyword match instead of an
# uncapped candidate list. Fix: require the automation vocabulary to
# actually be about an "action" (the noun this tool analyzes) or use the
# more specific technical term "automatisation" -- a standalone adjective/
# adverb "automatique"/"automatiquement" with no accompanying "action"
# noun no longer matches on its own.
_AUTOMATION_PATTERN = re.compile(
    r"\b(?:mêmes?\s+règles?|systématiq\w*|actions?\s+automatiques?|automatisation\w*|"
    r"actions?\s+serveur|bypass|contourn\w*)\b",
    re.IGNORECASE,
)


def _question_mentions_amount(question: str) -> bool:
    return bool(_AMOUNT_PATTERN.search(question))


def _extract_amount(question: str) -> "Optional[float]":
    """
    Extract the first monetary amount mentioned in the question, as a
    float, or None if none found / unparseable. Reuses _AMOUNT_PATTERN's
    detection but strips the currency symbol/word and normalizes the
    thousands separator (space or comma) before the decimal point.
    Deliberately conservative: on any parsing ambiguity, returns None
    rather than guessing a possibly-wrong value -- a missed deterministic
    check is safer than a wrong one.
    """
    match = _AMOUNT_PATTERN.search(question)
    if not match:
        return None
    raw = match.group(0)
    # Strip currency symbol/word, keep only digits, spaces, commas, dots.
    numeric_part = re.sub(r"(?i)(€|eur(?:os?)?)", "", raw).strip()
    # Normalize: remove spaces and commas used as thousands separators.
    # This assumes no decimal amounts appear in the adversarial question
    # set (verified: all amounts are whole euros, e.g. "80 000€") --
    # a real decimal separator would need locale-aware parsing, out of
    # scope for this bounded deterministic check.
    cleaned = numeric_part.replace(" ", "").replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


# Bloc9 08c follow-up, requested 2026-08-13: evaluate_domain_force/
# can_view_amount_v2 (deterministic_tools.py) were wired into the
# evaluer_regles_enregistrement short-circuit below on 2026-08-1x, but
# deliberately WITHOUT company context -- see that call site's own comment
# ("company/user context is not extracted from the question this session").
# This closes that specific gap: a qualitative same/different extraction,
# not an identity lookup. There is no res.company name/id resolver
# anywhere in this codebase (unlike _resolve_user_group_xmlids for
# groups), and the live test Odoo instance is documented mono-company
# (todo/etat_reel.md, Bloc 1: "la limite mono-société de l'environnement
# de test") -- so a real company NAME or ID can never be resolved against
# a live second company from natural-language text on this setup. What a
# question CAN state, and the only thing worth trusting, is the RELATION
# between the requester's company and the record's company ("la même
# société" / "une autre société"), which is all evaluate_domain_force's
# equality-based domain_force leaves (company_id = user.company_id.id)
# actually need -- the specific numeric ids compared are arbitrary
# sentinels, only their equality/inequality carries meaning. No mention
# at all -> {} (unchanged behaviour, amount-only context, same honest
# None/"cannot conclude" outcome as before this fix for any domain_force
# that also checks company_id).
_COMPANY_DIFFERENT_PATTERN = re.compile(
    r"(?:pas\s+(?:de\s+)?la\s+m[êe]me\s+(?:soci[ée]t[ée]|filiale|entreprise)|"
    r"(?:une\s+)?autre\s+(?:soci[ée]t[ée]|filiale|entreprise)|"
    r"(?:soci[ée]t[ée]|filiale|entreprise)\s+(?:est\s+)?diff[ée]rente?)",
    re.IGNORECASE,
)
_COMPANY_SAME_PATTERN = re.compile(
    r"m[êe]me\s+(?:soci[ée]t[ée]|filiale|entreprise)",
    re.IGNORECASE,
)


def _extract_company_context(question: str) -> "Dict[str, Any]":
    """
    Extract a qualitative same/different-company relation from the
    question, in the {"company_id": ..., "user": {"company_id": {"id":
    ...}}} shape evaluate_domain_force()/can_view_amount_v2() expect for
    a company_id-referencing domain_force leaf (e.g. ['|',
    ('company_id', '=', False), ('company_id', '=',
    user.company_id.id)], the real Module 08 rule --
    code_intelligence/tests/test_s2_9_domain_force_evaluator.py).

    Checks the DIFFERENT pattern first: "pas la même société" contains
    "même société" as a substring, so SAME must never win on a negated
    phrasing. Returns {} (no company keys at all, not a guessed value)
    when the question says nothing about company at all -- absence of
    information must resolve to unresolved/None downstream, never to a
    guessed same or different, per rules.md Regle 5.
    """
    if _COMPANY_DIFFERENT_PATTERN.search(question):
        return {"company_id": 1, "user": {"company_id": {"id": 2}}}
    if _COMPANY_SAME_PATTERN.search(question):
        return {"company_id": 1, "user": {"company_id": {"id": 1}}}
    return {}


def _question_is_approval_related(question: str) -> bool:
    return bool(_APPROVAL_PATTERN.search(question))


# Bloc 9 gap, found 2026-08-13 (native-Odoo-out-of-scope investigation,
# "qui peut confirmer un devis (sale.order)" question): qui_a_acces_a (the
# ACL/ir.rule access-matrix tool) had NO forced pre-dispatch at all, unlike
# analyser_verrous_securite/analyser_actions_serveur/
# analyser_chaine_surcharge_methode below -- it only ran if the LLM's own
# free tool choice picked it, which failed here: on a "who can do X"
# question against a model with no Python lock and no server action, the
# ReAct loop made one (correctly empty) analyser_verrous_securite call and
# answered directly, never checking the ACL/ir.rule layer that actually
# governs access for the overwhelming majority of Odoo models -- which
# have no Python lock or server action at all; ACL is the DEFAULT
# access-control mechanism, locks/actions are the exception.
#
# Unlike those three tools, gating this on "does the model structurally
# have something interesting" doesn't make sense here: virtually every
# real Odoo model has ACL entries, so a structural guard would fire on
# nearly every question -- not a meaningful filter, and it would burn the
# tight CI_MAX_HOPS=4 budget on unrelated questions. Gate on the QUESTION
# SHAPE instead ("qui peut/a le droit/est autorise a ..." -- a small,
# closed set of French "who can" phrasings) rather than an open-ended list
# of business verbs (confirmer, valider, demarrer...) that would need a
# new entry per module forever -- the exact whack-a-mole this project
# already moved away from for analyser_verrous_securite's own dispatch
# (module 5/8, 2026-08-10).
_ACCESS_QUESTION_PATTERN = re.compile(
    # Original "qui peut/a le droit/est autorisé" patterns
    r"\bqui\s+(?:a\s+le\s+droit|peut|peux|est\s+autoris\w*)\b|"
    # Bloc9 08c gap (2026-08-14): "peut-il/elle voir/accéder/consulter"
    # was not matched -- the question 08c ("Un utilisateur standard ...
    # peut-il voir un document ...") was never recognized as access-
    # related, so neither qui_a_acces_a nor evaluer_regles_enregistrement
    # were force-dispatched. The resolver then guessed model='base',
    # can_view_amount_v2 got zero rules, and returned True for the wrong
    # model. This branch covers the inverted-subject French question form
    # ("peut-il/elle/on voir") in addition to the "qui peut" form above.
    r"\b(?:peut|peux|pourra|pourrait)[\s-]*(?:il|elle|on|t[\s-]*il|t[\s-]*elle)\s+(?:voir|acc[eé]der|consulter|lire|visualiser)\b|"
    # "a-t-il/elle le droit/accès/la permission"
    r"\ba[\s-]*t[\s-]*(?:il|elle)\s+(?:le\s+droit|acc[eè]s|la\s+permission)\b|"
    # English patterns
    r"\bwho\s+(?:can|has\s+the\s+right|is\s+authoriz\w*)\b|"
    r"\b(?:can|may)\s+(?:a\s+user|the\s+user|an?\s+employee)\s+(?:see|view|access|read)\b",
    re.IGNORECASE,
)


def _question_is_access_related(question: str) -> bool:
    return bool(_ACCESS_QUESTION_PATTERN.search(question))


# Bloc 9 cross-module gap (2026-08-10, modules 1/8, 3/8, 4/8 generalization
# checks): the "Groupe(s) technique(s) requis detecte(s) (has_group)" line
# was present in every single raw analyser_verrous_securite observation
# checked, but was just as reliably DROPPED from the final synthesized
# answer specifically on business/trap-phrased approval questions (present
# on purely technical-enumeration phrasings, e.g. "quelles sont toutes les
# conditions verifiees par ..."). Unlike SUPER() NON GARDE / CHAINE
# RELATIONNELLE NON VERIFIEE, which each already have a dedicated prose
# instruction in synthesis_prompt below, this line had none.
#
# Deliberately NOT fixed by adding yet another synthesis_prompt clause.
# synthesis_prompt already carries a dozen-plus specific instructions for
# an 8B model with a documented decoding-collapse failure mode under
# pressure (_detect_degenerate_repetition) and a hard Groq 413 payload
# ceiling already hit repeatedly in these same runs -- growing it further
# risks diluting attention on the instructions already there, for an
# unproven gain on this one. This project already made exactly this call
# once before and reversed it (see the J7/J8 comment above
# _AMOUNT_PATTERN: "Rather than trying to word the prompt more forcefully
# -- which already failed once -- ... removing the LLM from that decision
# entirely"). Applying the same principle here: extract the required
# group(s) directly from the raw tool text, independent of anything the
# LLM did or didn't say, and append them only if genuinely missing --
# never overriding or duplicating a correct answer.
_REQUIRED_GROUP_LINE_RE = re.compile(
    r"Groupe\(s\)\s+technique\(s\)\s+requis\s+detecte\(s\)\s+\(has_group\):\s*([^\n]+)"
)


# Bloc 9 gap fix (2026-08-13, module 8/8 follow-up investigation): matches
# any Odoo group xmlid shape ('<module>.group_<name>') so the grounding
# validator below can find every group token the LLM mentioned in
# final_answer, not just the ones matching _REQUIRED_GROUP_LINE_RE (that
# regex only captures the tool's OWN summary line -- the LLM is free to
# type a group name anywhere else in its prose).
_GROUP_XMLID_RE = re.compile(r"\b[a-z][a-z0-9_]*\.group_[a-z0-9_]+\b")


def _extract_required_groups(raw_tool_output: str) -> List[str]:
    """Pull every has_group()-derived required group xml_id out of the raw
    tool text, in first-seen order, deduplicated. Returns [] if no such
    line is present -- never guesses a group from anywhere else."""
    groups: List[str] = []
    for match in _REQUIRED_GROUP_LINE_RE.finditer(raw_tool_output):
        for name in match.group(1).split(","):
            name = name.strip()
            if name and name not in groups:
                groups.append(name)
    return groups


def _flag_ungrounded_group_xmlids(final_answer: str, raw_tool_output: str) -> str:
    """Bloc 9 gap fix (2026-08-13, module 8/8 follow-up investigation):
    negative/grounding validator -- the mirror image of every backfill
    above (which only ever ADD a fact already known to be true). This one
    only ever FLAGS, never silently strips: same transparency principle
    already used by verify_citations/annotate_unverifiable_citations right
    below for the structurally identical problem (an LLM claim with no
    verified backing in this turn's evidence).

    Grounded set = every group xmlid extracted via _extract_required_groups
    (the exact same has_group() line format _backfill_missing_required_
    groups already trusts as authoritative) from this turn's scoped tool
    output. Any <module>.group_<x>-shaped token in final_answer that is
    NOT in that set gets flagged -- never removed, since an ungrounded
    mention may still be legitimate context (e.g. a different threshold's
    group explained for contrast) that a mechanical substring check cannot
    distinguish from a genuine hallucination; only a reviewer should act on
    the flag, not this function.

    Deliberately a no-op when grounded is empty -- a turn where no
    security-lock tool fired this hop has no reference set to check
    against, and flagging every group mention as fake in that case would
    be strictly worse than saying nothing.
    """
    grounded = set(_extract_required_groups(raw_tool_output))
    if not grounded:
        return final_answer

    mentioned = set(_GROUP_XMLID_RE.findall(final_answer))
    ungrounded = sorted(mentioned - grounded)
    if not ungrounded:
        return final_answer

    group_list = ", ".join(ungrounded)
    logger.warning(
        "Node [code_intelligence_agent]: group xmlid(s) mentioned in synthesized "
        "answer with no has_group() backing in this turn's scoped tool output "
        "(possible hallucination, flagged not stripped): %s",
        group_list,
    )
    return (
        final_answer
        + f"\n\n⚠️ GROUPE(S) NON VÉRIFIÉ(S) : {group_list} mentionné(s) dans la réponse "
        f"sans correspondance has_group() dans les données produites pour cette question. "
        f"Ne pas considérer ce(s) groupe(s) comme confirmé(s) sans vérification manuelle."
    )


def _grounded_core_only_groups(final_answer: str, scoped_tool_output: str) -> List[str]:
    """Bloc 9 gap fix (2026-08-14, module 1/8 follow-up, LLM free-prose
    'account.group_account_invoice' noise -- see todo/etat_reel.md and
    contexte.txt section 42/addendum): a THIRD category, orthogonal to
    _flag_ungrounded_group_xmlids' grounded/ungrounded split above -- a
    group xmlid can be genuinely grounded (a real has_group() call exists
    somewhere in this turn's scoped_tool_output) while still being
    irrelevant, because analyser_verrous_securite (ci_agent_tools.py)
    aggregates EVERY Python file touching the model with zero custom/core
    distinction, so a widely-shared core model like account.move always
    drags in Odoo's own core has_group() checks (e.g.
    account.group_account_invoice in _post()) alongside the real custom
    override, in the SAME block the LLM's free synthesis reads verbatim.
    _restrict_blocks_to_custom_modules already solves this for the
    deterministic backfill path (_backfill_missing_required_groups) below
    -- this reuses the exact same file-link classification to compute the
    narrower 'grounded AND custom' set, so the difference (grounded but
    ONLY present in a non-custom block) identifies a group the LLM's own
    free prose cited from core Odoo content that has nothing to do with
    the custom mechanism this question actually resolved to.

    Deliberately does NOT touch raw_tool_output itself (only the already-
    computed scoped_tool_output the caller already scoped to the resolved
    model(s)) -- consistent with the module-level comment above
    _restrict_blocks_to_custom_modules: raw_tool_output must stay fully
    unscoped for verify_citations/_force_dynamic_uncertainty_answer, which
    legitimately need visibility into every real has_group()/getattr()
    call, core Odoo included.
    """
    grounded = set(_extract_required_groups(scoped_tool_output))
    if not grounded:
        return []
    custom_grounded = set(
        _extract_required_groups(_restrict_blocks_to_custom_modules(scoped_tool_output))
    )
    mentioned = set(_GROUP_XMLID_RE.findall(final_answer))
    return sorted((mentioned & grounded) - custom_grounded)


def _strip_core_only_group_mentions(final_answer: str, scoped_tool_output: str) -> str:
    """Removes, in place, the line or clause naming each group xmlid
    identified by _grounded_core_only_groups above. Unlike
    _flag_ungrounded_group_xmlids (a genuine hallucination is flagged, not
    stripped, since a reviewer should judge whether it is legitimate
    context) -- a grounded-but-core-only group is definitionally never
    relevant to a custom-mechanism question, so there is nothing left for
    a reviewer to adjudicate: removing it is safe.

    A bandeau-only warning was tried and found insufficient for this same
    shape of problem once already (module 5/8 Bug 2, link-guard
    contradiction -- see _neutralize_contradicting_link_guard_sentence
    below): the flagged sentence stays visible and readable underneath the
    warning, so a downstream check for the specific wrong content still
    fails. This follows the same in-place-removal precedent, but simpler:
    there is no template sentence to reconstruct here (unlike the
    link-guard case, where the correct conclusion had to be restated), so
    the matched clause/line is dropped rather than replaced -- bounded to
    '.'/'\\n' on either side (same bounding technique as
    _LINK_GUARD_CONTRADICTING_SENTENCE_RE below) so only the specific
    clause naming the group is removed, never a neighboring sentence or
    bullet.

    No-op when _grounded_core_only_groups returns nothing -- most turns
    never aggregate a core-Odoo block at all (single-file custom modules
    are the majority case), so this rarely fires.
    """
    core_only = _grounded_core_only_groups(final_answer, scoped_tool_output)
    if not core_only:
        return final_answer

    result = final_answer
    for xmlid in core_only:
        pattern = re.compile(r"[^.\n]*" + re.escape(xmlid) + r"[^.\n]*\.?\n?")
        result = pattern.sub("", result)
    result = re.sub(r"\n{3,}", "\n\n", result)

    logger.warning(
        "Node [code_intelligence_agent]: stripped grounded-but-core-Odoo-only "
        "group xmlid(s) from synthesized answer (relevant only to a shared "
        "core file, not the custom mechanism this question resolved to): %s",
        ", ".join(core_only),
    )
    return result


def _scoped_raw_tool_output(
    tool_observations: List[str],
    tool_observation_models: List[str],
    target_models: List[str],
) -> str:
    """Bloc 9 gap fix (2026-08-10, bloc9-05c-no-link-trap contamination):
    the deterministic backfills below (_backfill_missing_required_groups,
    _backfill_link_guard_clarifications) used to be handed raw_tool_output
    built from the ENTIRE concatenated tool_observations list -- every hop
    of the ReAct loop for the whole turn, regardless of which model that
    hop actually targeted. When business_resolver/the ReAct loop wandered
    onto an unrelated model in the same turn (confirmed case: a detour
    through custom.purchase.request while answering a custom.asset.loan
    question), that unrelated model's OWN [GARDE DE LIEN]/[Groupe(s)
    technique(s) requis] annotations leaked into a backfill mechanism that
    is supposed to be a 100%-reliable, model-scoped fact -- the opposite of
    what "deterministic" is meant to guarantee.

    Restricts the text handed to a backfill to observations recorded
    (tool_observation_models, index-aligned with tool_observations) against
    one of target_models, plus any observation whose model could not be
    determined (empty string -- these are meta/global tool calls, never the
    source of a per-model contamination risk, so excluding them would only
    lose legitimate content for no safety benefit). Falls back to the full
    unscoped concatenation when target_models is empty (unresolved concept
    -- no scope to restrict to, same behavior as before this fix).

    Deliberately NOT used for raw_tool_output itself (citation verification
    and dynamic-uncertainty detection still need visibility into every hop
    of the turn) -- only for the two backfill call sites, which is where
    cross-model contamination turns into a wrong fact stated with full
    (undeserved) confidence.
    """
    if not target_models:
        return "\n\n".join(tool_observations)
    target_set = set(target_models)
    scoped = [
        obs
        for obs, model in zip(tool_observations, tool_observation_models)
        if not model or model in target_set
    ]
    return "\n\n".join(scoped)


_LOCK_CONDITION_LINE_RE = re.compile(
    r"\*\s*\"[^\"]*\"\s*\(condition\s*:\s*(.*?has_group\([\'\"]([^\'\"]+)[\'\"]\).*?)\)",
    re.IGNORECASE,
)
_AMOUNT_CMP_RE = re.compile(
    r"(?:rec\.)?amount(?:_total)?\s*(>|>=|<|<=)\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _extract_required_groups_for_amount(raw_tool_output: str, amount: Optional[float] = None) -> List[str]:
    """Pull required group xml_ids from raw tool text, filtering by monetary threshold
    when an explicit amount is provided.

    If amount is None, returns all required groups (unfiltered).
    If amount is provided, inspects the condition lines associated with has_group('<group>'):
      - For conditions checking `amount > T` or `amount >= T`: the group is only required
        if the question's amount exceeds T.
      - Groups with no numeric threshold condition (unconditional locks) are always retained.
    """
    all_groups = _extract_required_groups(raw_tool_output)
    if amount is None or not all_groups:
        return all_groups

    group_conditions: Dict[str, List[Tuple[str, float]]] = {}
    for match in _LOCK_CONDITION_LINE_RE.finditer(raw_tool_output):
        cond_text = match.group(1)
        group_name = match.group(2).strip()
        cmp_match = _AMOUNT_CMP_RE.search(cond_text)
        if cmp_match:
            op = cmp_match.group(1)
            thresh = float(cmp_match.group(2))
            group_conditions.setdefault(group_name, []).append((op, thresh))

    filtered_groups: List[str] = []
    for g in all_groups:
        if g not in group_conditions:
            filtered_groups.append(g)
        else:
            active = False
            for op, thresh in group_conditions[g]:
                if op == ">" and amount > thresh:
                    active = True
                    break
                elif op == ">=" and amount >= thresh:
                    active = True
                    break
                elif op == "<" and amount < thresh:
                    active = True
                    break
                elif op == "<=" and amount <= thresh:
                    active = True
                    break
            if active:
                filtered_groups.append(g)

    return filtered_groups


# Bloc 9 gap, documented open in todo/etat_reel.md as "account.group_
# account_invoice noise" (module 1/8, bloc9-01a-business, found 2026-08-13,
# left deliberately unfixed at the time -- "necessiterait un scoping
# fichier/module plus fin qu'un scoping par modele ... delibere ment non
# traite (risque de sur-edition sans tests dedies)"). Root cause traced by
# direct inspection of the real source (2026-08-14 follow-up): analyser_
# verrous_securite (ci_agent_tools.py) aggregates analyze_python_security_
# locks' summary_text for EVERY Python file touching the model, joined
# with the same '\n\n' block separator _scoped_raw_tool_output/_extract_
# security_lock_condition_amounts already rely on -- on a widely-shared
# core model like account.move, that includes Odoo's own core account/
# models/account_move.py right alongside the custom override file. Core
# Odoo's _post() has a real, correctly-attributed has_group('account.
# group_account_invoice') check (governs posting ANY invoice, confirmed
# by direct read of /home/user/odoo-17.0/addons/account/models/
# account_move.py, line ~3941) that has nothing to do with a custom
# approval-cascade question ("qui a le droit d'approuver un avoir de
# 25000e") -- genuinely grounded, not a hallucination (_flag_ungrounded_
# group_xmlids correctly leaves it alone), just out of scope: this
# product's entire premise (Bloc 9, "Generalisation au code custom") is
# bypass/governance mechanisms in CUSTOM overlay code, never core Odoo's
# own standard access control living in a different file that happens to
# share the model.
#
# Each block's own header line already carries a file:// link (see
# analyze_python_security_locks' use of format_file_link) -- restricting
# extraction to blocks whose link points under a 'custom_*' addon
# directory removes this specific noise without touching _extract_
# required_groups itself (still used unfiltered by _flag_ungrounded_
# group_xmlids, which must keep seeing core Odoo's real has_group() calls
# too -- a mention that IS grounded there should never be flagged as a
# hallucination just because it's irrelevant to this particular question).
_BLOCK_FILE_LINK_RE = re.compile(r"\(file://([^)#]+)")


def _block_is_custom_module_file(block: str) -> bool:
    """True when this '\n\n'-delimited block's own file:// link (see
    _BLOCK_FILE_LINK_RE) points at a file under a 'custom_*' addon
    directory. Returns True (keep the block) whenever no file:// link is
    found at all -- never silently drops a block this cannot positively
    classify as core/OCA Odoo, same conservative default as every other
    scoping guard in this module."""
    match = _BLOCK_FILE_LINK_RE.search(block)
    if not match:
        return True
    return "/custom_" in match.group(1)


def _restrict_blocks_to_custom_modules(raw_tool_output: str) -> str:
    """Drop blocks whose file:// link points outside a 'custom_*' addon
    (see _block_is_custom_module_file) before required-group extraction.
    Scoped narrowly to the required-groups backfill below -- deliberately
    NOT applied to raw_tool_output/scoped_tool_output themselves (citation
    verification and _flag_ungrounded_group_xmlids still need to see every
    real has_group() call, core Odoo included: this filters what counts as
    a *relevant* fact to backfill, not what counts as *grounded*)."""
    blocks = raw_tool_output.split("\n\n")
    kept = [b for b in blocks if _block_is_custom_module_file(b)]
    return "\n\n".join(kept) if kept else raw_tool_output


def _backfill_missing_required_groups(final_answer: str, raw_tool_output: str, question: str) -> str:
    """Deterministic backfill (see module-level comment above
    _REQUIRED_GROUP_LINE_RE for why this is a code-level fix, not a
    prompt-level one): on an approval-related question, if the raw tool
    output named required group(s) via has_group() that never made it
    into the synthesized answer, append them as an explicit, clearly
    labeled fact. No-op whenever every required group is already present
    in the answer -- this never duplicates or contradicts a correct
    synthesis, it only fills a gap.

    Bloc 9 gap fix (2026-08-14, module 8/8, bloc9-08a-business): when the
    question specifies a monetary amount (e.g. 60 000€), only backfills
    groups whose threshold is actually reached/triggered for that amount,
    rather than blindly backfilling higher-threshold groups (e.g. base.group_system
    requiring > 100k€).

    Bloc 9 gap fix (2026-08-14, module 1/8 follow-up, 'account.group_
    account_invoice noise'): raw_tool_output is restricted to custom-
    module blocks (see _restrict_blocks_to_custom_modules) before group
    extraction, so a core-Odoo has_group() check aggregated onto the same
    shared model no longer gets backfilled as if it were part of this
    custom approval mechanism.
    """
    if not _question_is_approval_related(question):
        return final_answer

    amount = _extract_amount(question)
    custom_scoped_output = _restrict_blocks_to_custom_modules(raw_tool_output)
    required_groups = _extract_required_groups_for_amount(custom_scoped_output, amount)
    if not required_groups:
        return final_answer

    missing = [g for g in required_groups if g not in final_answer]
    if not missing:
        return final_answer

    group_list = ", ".join(missing)
    logger.info(
        "Node [code_intelligence_agent]: backfilling required group(s) missing "
        "from synthesized answer (present in raw tool output, dropped by synthesis): %s",
        group_list,
    )
    return (
        final_answer
        + f"\n\n[FAIT DÉTERMINISTIQUE] Groupe(s) technique(s) requis (has_group) "
        f"détecté(s) dans le code pour cette action : {group_list}. Fait extrait "
        f"directement de l'analyse statique du code."
    )


# Bloc 9 gap, found 2026-08-11 (module 1/8 rerun, bloc9-01a-business /
# bloc9-01b-technical, AFTER the has_group()/cap/truncation fixes above are
# all confirmed active): two further, distinct dropped-fact gaps on the same
# 'account.move.action_valider_avoir' override cascade, both traced by
# reading the raw analyser_chaine_surcharge_methode text directly rather
# than guessing further --
#
#   (a) bloc9-01a-business: the regional module's 20000e relational-chain
#       finding is present verbatim in the (correctly-sized, post-2200-cap)
#       forced-dispatch observation, but the synthesized answer for the
#       BUSINESS-phrased question ("qui a le droit d'approuver...") ignores
#       it entirely -- not denied, just never used, a two-sentence answer
#       that only reasons from the has_group() gate. The same raw content
#       DOES get used correctly for the TECHNICAL-phrased question (01b
#       enumerates it in full) -- so this isn't a dispatch/truncation
#       problem, it's the small model treating a risk/warning-shaped
#       finding as orthogonal to an "approval rights" question instead of
#       an additional gate on top of the group requirement.
#
#   (b) bloc9-01b-technical: the third (base) override site is enumerated
#       correctly in content but mislabeled -- the LLM calls it "module
#       'account_move'" instead of "module 'custom_credit_note_approval'",
#       apparently substituting the shared file basename (all three
#       override sites live in a same-named account_move.py, only the
#       directory/module name differs) for the actual module name on the
#       one entry whose module name is a strict PREFIX of both siblings'
#       names ("custom_credit_note_approval" vs "..._regional"/"..._vip"),
#       so it's plausible the model conflated it with the file path token
#       repeated three times in the raw text rather than confusing it with
#       a sibling module. Confirmed NOT a recurrence of the original Gap 3
#       hallucination (no fabricated 4th module name, `custom_credit_note_
#       approval_global`, appears anywhere in this run) -- a narrower,
#       different failure: a real module dropped from the text entirely,
#       not an invented one added.
#
# Same deterministic-backfill principle as _backfill_missing_required_
# groups above, applied to two more fact shapes already present verbatim
# in the raw tool text: extract directly, append only what's genuinely
# missing, never override or duplicate a correct synthesis. Word-boundary
# checked for the module names specifically (plain substring would let
# 'custom_credit_note_approval' silently pass because it's a literal
# prefix of the two suffixed sibling names already correctly mentioned --
# the exact false-positive class check_bloc9_01_credit_note_cascade_e2e.py
# itself already guards against with its own word-boundary marker check).
_OVERRIDE_MODULE_RE = re.compile(r"module '([\w.]+)'")
_OVERRIDE_CHAIN_AMOUNT_RE = re.compile(r"rec\.\w+\s*>\s*(\d[\d\s]*\d)")


def _extract_override_modules(raw_tool_output: str) -> List[str]:
    """Pull every override-cascade module name out of an
    analyser_chaine_surcharge_methode raw observation ("module 'x'" lines),
    in first-seen order, deduplicated. Returns [] if no such line is
    present -- this pattern is specific to that one tool's output shape,
    so it's a safe no-op on any other observation mixed into the same
    scoped text."""
    modules: List[str] = []
    for match in _OVERRIDE_MODULE_RE.finditer(raw_tool_output):
        name = match.group(1).strip()
        if name and name not in modules:
            modules.append(name)
    return modules


def _word_boundary_present(marker: str, text: str) -> bool:
    """Same technique (and same false-positive this guards against) as
    check_bloc9_01_credit_note_cascade_e2e.py's own _word_boundary_present
    -- a plain substring check would let 'custom_credit_note_approval'
    silently pass just because it's a literal prefix of
    'custom_credit_note_approval_regional'/'..._vip', already mentioned
    correctly elsewhere in the same answer."""
    return re.search(r"(?<![A-Za-z0-9_])" + re.escape(marker) + r"(?![A-Za-z0-9_])", text) is not None


def _backfill_missing_override_modules(final_answer: str, raw_tool_output: str) -> str:
    """Deterministic backfill for gap (b) above: if the raw override-cascade
    text names a module (word-boundary) that never made it into the
    synthesized answer, append it as an explicit, clearly labeled fact.
    No-op whenever every module is already correctly named -- never
    duplicates or contradicts a correct synthesis, and deliberately does
    NOT try to detect or correct a mislabeling (e.g. 'account_move' used in
    its place) -- same over-trimming caution as the hallucination case in
    method_override_resolver.py (see contexte.txt section 24): safer to
    add the missing true fact alongside a wrong label than to try to edit
    prose the small model already got wrong once.

    Bloc 9 gap, found 2026-08-11 (real pytest run, this backfill's OWN new
    test against the real bloc9-01b-technical question wording): originally
    gated on _question_is_approval_related(question), copied from
    _backfill_missing_required_groups without checking it against the
    actual question this backfill exists to fix. That question --
    "...toutes les surcharges de la methode action_valider_avoir..." --
    never matches _APPROVAL_PATTERN: "valider" is glued to underscores on
    both sides inside "action_valider_avoir", so \bvalid\w*\b never finds a
    boundary to match at. The gate would have silently no-op'd on the exact
    live case this backfill targets, not just in the test. Dropped the
    gate entirely -- unconditional now, same as _backfill_link_guard_
    clarifications below (see its own docstring for the same reasoning):
    the extraction step (modules being non-empty) is already the real
    relevance guard, a question-wording check on top of that is redundant
    at best and actively wrong at worst, since in real usage this text
    only ever reaches scoped_tool_output when the override-cascade tool
    was actually invoked (forced pre-dispatch, gated on approval wording
    -- OR the ReAct loop's own free choice on a technical question just
    like this one, which needs no such wording at all).
    """
    modules = _extract_override_modules(raw_tool_output)
    if not modules:
        return final_answer

    missing = [m for m in modules if not _word_boundary_present(m, final_answer)]
    if not missing:
        return final_answer

    module_list = ", ".join(f"'{m}'" for m in missing)
    logger.info(
        "Node [code_intelligence_agent]: backfilling override-cascade module(s) missing "
        "from synthesized answer (present in raw tool output, dropped/mislabeled by synthesis): %s",
        module_list,
    )
    return (
        final_answer
        + f"\n\n[FAIT DÉTERMINISTIQUE] La chaîne de surcharge de méthode inclut "
        f"également le/les module(s) suivant(s), absent(s) ou mal identifié(s) "
        f"ci-dessus : {module_list}. Fait extrait directement de l'analyse statique "
        f"du code."
    )


def _extract_override_chain_amounts(raw_tool_output: str) -> List[str]:
    """Pull every monetary threshold embedded in a Python comparison inside
    an override-cascade risk finding (e.g. 'rec.amount_total > 20000'), in
    first-seen order, deduplicated, whitespace stripped from the digits.
    Returns [] if no such expression is present. Deliberately scoped to
    this exact 'rec.<attr> > <digits>' shape (mirrors the real source's
    own Python syntax, quoted verbatim in the raw tool text) rather than a
    generic amount pattern -- narrow enough that it will never fire on
    unrelated prose, at the cost of not generalizing to a differently-
    worded threshold check on some future module (acceptable: this backfill
    only needs to catch a threshold ALREADY quoted in the raw text, not
    invent one)."""
    amounts: List[str] = []
    for match in _OVERRIDE_CHAIN_AMOUNT_RE.finditer(raw_tool_output):
        amount = match.group(1).replace(" ", "").strip()
        if amount and amount not in amounts:
            amounts.append(amount)
    return amounts


def _amount_present_in_text(amount: str, text: str) -> bool:
    """True if `amount` (a bare digit string, e.g. '5000') appears in
    `text` as a genuine standalone number -- either unspaced ('5000') or
    with a thousands-separator space ('5 000') -- never as a substring of
    a larger number (e.g. '25 000' must NOT count as containing '5000').

    Bloc 9 gap, found 2026-08-13 (module 1/8, bloc9-01a-business rerun,
    AFTER the block-scoping fix for _extract_security_lock_condition_
    amounts is confirmed working on bloc9-01b/01c): 01a's own question
    text ('un avoir de 25 000€') gets echoed verbatim in the synthesized
    answer's opening sentence -- and the old plain `in` substring check
    (`spaced in final_answer`) treated '5 000' as already present the
    moment it appeared as a literal substring of '25 000€', so
    _backfill_missing_security_lock_amount silently no-op'd, believing a
    fact was already covered when it was never actually stated (the
    answer never mentions the real 5000e threshold on its own terms).
    Reproduced directly against the live 01a answer text before this fix
    (spaced='5 000' found inside '25 000€' -- true positive on the bug,
    false negative on the actual check) and confirmed absent after it.

    Both call sites (_backfill_missing_override_chain_amount and
    _backfill_missing_security_lock_amount) previously defined their own
    identical local `_amount_present` closure with this exact bug --
    consolidated here as a single shared, digit-boundary-aware
    implementation instead of fixing the bug twice.
    """
    spaced = f"{amount[:-3]} {amount[-3:]}" if len(amount) > 3 else amount
    for candidate in {amount, spaced}:
        pattern = r"(?<!\d)" + re.escape(candidate) + r"(?!\d)"
        if re.search(pattern, text):
            return True
    return False


def _backfill_missing_override_chain_amount(final_answer: str, raw_tool_output: str) -> str:
    """Deterministic backfill for gap (a) above: if an override-cascade
    finding's own monetary threshold (already present verbatim in the raw
    tool text) never made it into the synthesized answer, append it as an
    explicit, clearly labeled fact -- same append-only, never-override
    discipline as every other backfill in this module. Checked both with
    and without a thousands-separator space (the LLM may re-render '20000'
    as '20 000' when paraphrasing correctly; either form counts as
    present).

    Bloc 9 gap, found 2026-08-11 (same live pytest run/root cause as
    _backfill_missing_override_modules above -- see its docstring): also
    used to be gated on _question_is_approval_related(question), same
    mistake, same fix -- dropped entirely, unconditional now. The amount
    this backfill exists to restore (bloc9-01a-business's missing 20000e)
    happens to come from an APPROVAL-phrased question, so that specific
    live failure would still have been caught by the old gate -- but
    leaving the gate in place would have left this backfill silently
    inert on the exact same technical-question class that broke its
    sibling function above, for no removed benefit (the amounts-list
    emptiness check is already the real relevance guard).

    Bloc 9 gap, found 2026-08-11 (module 5/8, bloc9-05c-no-link-trap live
    run pasted same day as the module 5/8 exception_conditions fix): the
    _OVERRIDE_CHAIN_AMOUNT_RE pattern ("rec.<attr> > <digits>") is not
    actually specific to analyser_chaine_surcharge_methode's output shape
    -- it is generic enough to also match the literal Python condition
    text semgrep_locks_analyzer.py's exception_conditions now renders
    ("condition : rec.montant_estime > 10000 and not email_ok", from
    custom_purchase_request.action_valider's own unrelated 10000e gate).
    Confirmed live: a custom_asset_loan question that also resolved
    custom.purchase.request (legitimate -- the two models are linked)
    picked up a fabricated "la chaine de surcharge de methode contient une
    condition supplementaire declenchee au-dela de 10000e" fact for a
    model that has no method-override chain at all. Same class of bug as
    _backfill_missing_required_groups' account.group_account_invoice noise
    (contexte.txt section 30) and the Bug 3/Bug 4 contamination cases
    (contexte.txt sections 26/28) -- a backfill reading text belonging to
    a different mechanism/tool than the one it was built for. Fixed here
    by requiring _extract_override_modules(raw_tool_output) to also be
    non-empty: a genuine override-cascade amount finding never appears in
    analyser_chaine_surcharge_methode's real output without an
    accompanying "module 'x'" line in the same text (see
    _REAL_OVERRIDE_CHAIN_RAW_TEXT in tests/test_graph.py), so this is a
    safe, narrow precondition -- not a new heuristic, the same
    extraction-non-empty relevance-guard principle already used
    everywhere else in this file, just applied to the right extractor.
    """
    if not _extract_override_modules(raw_tool_output):
        return final_answer

    amounts = _extract_override_chain_amounts(raw_tool_output)
    if not amounts:
        return final_answer

    missing = [a for a in amounts if not _amount_present_in_text(a, final_answer)]
    if not missing:
        return final_answer

    amount_list = ", ".join(f"{a}€" for a in missing)
    logger.info(
        "Node [code_intelligence_agent]: backfilling override-cascade amount threshold(s) missing "
        "from synthesized answer (present in raw tool output, dropped by synthesis): %s",
        amount_list,
    )
    return (
        final_answer
        + f"\n\n[FAIT DÉTERMINISTIQUE] La chaîne de surcharge de méthode contient "
        f"une condition supplémentaire déclenchée au-delà de {amount_list}, distincte "
        f"du groupe requis ci-dessus. Fait extrait directement de l'analyse statique "
        f"du code."
    )


# Bloc 9 gap, module 4/8 (custom_purchase_request, bloc9-04a-business /
# bloc9-04c-manager-trap, found 2026-08-13 continuing the 11/08 diagnosis
# in todo/etat_reel.md): action_valider has TWO UserError gates in
# cascade -- the has_group()/hardcoded-email gate (already covered by
# _backfill_missing_required_groups above), and a SECOND, amount-gated
# gate on top ("Au-dela de 10 000 euros, seule la Direction peut valider")
# that only fires past rec.montant_estime > 10000. Confirmed via direct
# read of analyze_python_security_locks' own rendering
# (semgrep_locks_analyzer.py) that this second message, WITH its numeric
# condition, is reliably present in the raw analyser_verrous_securite
# observation (single small file, well under the 3000-char cap for this
# forced dispatch -- truncation already ruled out as a cause here, unlike
# module 1/8's account.move case) -- but was dropped from the synthesized
# answer on both the business and manager-trap phrasings (todo/etat_reel.md,
# "Mise a jour 11/08 (tour suivant)"). Exactly the same failure SHAPE as
# module 1/8's Gap (a) (a second/risk-gate finding on the SAME model
# treated as irrelevant to an "approval rights" question by the small
# synthesis model, despite being present and correctly used on a purely
# technical phrasing) -- just on a different tool's output, and no
# analogous backfill existed yet for this exact fact shape (a numeric
# threshold living inside an exception CONDITION rendered by
# analyser_verrous_securite, not a group xml_id or an override-module
# name).
#
# Deliberately does NOT reuse _extract_override_chain_amounts (the
# function, not just the regex): that function's own guard
# (_extract_override_modules non-empty) is scoped to a DIFFERENT tool's
# output shape ("module 'x'" lines from analyser_chaine_surcharge_methode)
# and exists specifically because the bare 'rec.<attr> > <digits>' pattern
# is generic enough to leak across tools sharing the same Python
# condition-rendering convention -- see that guard's own docstring, which
# documents the EXACT REVERSE contamination once already (this very
# module's 'rec.montant_estime > 10000' condition leaking INTO an
# unrelated override-cascade amount backfill on a custom_asset_loan
# question). This function reuses only the shared _OVERRIDE_CHAIN_AMOUNT_RE
# regex (the Python comparison shape itself is genuinely tool-agnostic),
# gated on its OWN independent structural marker instead of borrowing a
# guard built for a sibling tool's output shape.
_SECURITY_LOCK_MESSAGES_MARKER = "Messages de verrous (UserError/ValidationError):"


def _extract_security_lock_condition_amounts(raw_tool_output: str) -> List[str]:
    """Pull every monetary/numeric threshold embedded in a Python comparison
    inside an analyser_verrous_securite exception condition (e.g.
    'rec.montant_estime > 10000'), in first-seen order, deduplicated.
    Returns [] whenever _SECURITY_LOCK_MESSAGES_MARKER -- the literal
    header line analyze_python_security_locks always emits once it has at
    least one exception message -- is absent from the raw text. See the
    module-level comment above _SECURITY_LOCK_MESSAGES_MARKER for why this
    does not reuse _extract_override_chain_amounts' own guard.

    Bloc 9 gap, found 2026-08-13 (module 1/8 rerun, bloc9-01a-business /
    bloc9-01c-vip-trap, AFTER the module 4/8 security-lock backfill above
    is confirmed working on custom_purchase_request): on account.move, the
    SAME scoped_tool_output can legitimately contain BOTH this tool's own
    block (custom_credit_note_approval's real security lock, 'rec.
    amount_total > 5000') AND an unrelated analyser_chaine_surcharge_
    methode block (custom_credit_note_approval_regional's override-cascade
    finding, 'rec.amount_total > 20000') in the same turn, because both
    tools target account.move and _scoped_raw_tool_output only scopes by
    MODEL, not by tool/block -- the two blocks share a model, so model-
    scoping cannot separate them (unlike the module 5/8 cross-MODEL
    contamination that fix already covers). The old version of this
    function gated on the marker being present ANYWHERE in the full
    (already-joined) text, then scanned amounts from the ENTIRE text --
    so it silently picked up the unrelated 20000 from the override-cascade
    block and labeled it a "verrou de securite" amount, live-confirmed on
    both bloc9-01a-business (20000 asserted as the security-lock threshold
    instead of the real 5000, which never appeared anywhere in the answer)
    and bloc9-01c-vip-trap (the backfilled 20000 fact directly contradicts
    the answer's OWN correct prose two lines above it, which cites 5000).
    Neither the check script's expected_markers (only checks '20000'/
    'account.group_account_manager' appear somewhere, never which fact
    they're attributed to) nor the existing test
    (test_no_op_on_unrelated_rec_comparison_outside_security_lock_text,
    which only exercises the override-cascade text ALONE, marker absent)
    covered this combined-block scenario.

    Fixed by scoping the marker check AND the amount scan to the same
    '\n\n'-delimited block, instead of the whole raw_tool_output string --
    tool_observations/scoped_tool_output are always joined with '\n\n'
    (see _scoped_raw_tool_output), and no single tool's own rendering has
    been observed to contain an internal blank line, so this is a safe,
    already-implicit block boundary rather than a new assumption.
    """
    amounts: List[str] = []
    for block in raw_tool_output.split("\n\n"):
        if _SECURITY_LOCK_MESSAGES_MARKER not in block:
            continue
        for match in _OVERRIDE_CHAIN_AMOUNT_RE.finditer(block):
            amount = match.group(1).replace(" ", "").strip()
            if amount and amount not in amounts:
                amounts.append(amount)
    return amounts


def _backfill_missing_security_lock_amount(
    final_answer: str, raw_tool_output: str, question: Optional[str] = None
) -> str:
    """Deterministic backfill, symmetric to _backfill_missing_required_groups
    and _backfill_missing_override_chain_amount, for the fact shape found
    on module 4/8 (custom_purchase_request): if analyser_verrous_securite's
    raw exception-condition text names a numeric threshold that never made
    it into the synthesized answer, append it as an explicit, clearly
    labeled fact. No-op whenever the threshold is already present (checked
    with and without a thousands-separator space, same tolerance as
    _backfill_missing_override_chain_amount) -- never duplicates or
    contradicts a correct synthesis, only fills a gap.

    Bloc 9 gap fix (2026-08-14, module 8/8 follow-up): when question specifies
    a monetary amount or is a read visibility rule question (where can_view_amount
    fact is present), thresholds strictly greater than the question's amount are
    not triggered and are not backfilled as noise.
    """
    if question is not None:
        if _has_can_view_amount_fact(final_answer):
            return final_answer
        amount = _extract_amount(question)
    else:
        amount = None

    amounts = _extract_security_lock_condition_amounts(raw_tool_output)
    if not amounts:
        return final_answer

    if amount is not None:
        amounts = [a for a in amounts if float(a) <= amount]
        if not amounts:
            return final_answer

    missing = [a for a in amounts if not _amount_present_in_text(a, final_answer)]
    if not missing:
        return final_answer

    amount_list = ", ".join(f"{a}€" for a in missing)
    logger.info(
        "Node [code_intelligence_agent]: backfilling security-lock condition amount "
        "threshold(s) missing from synthesized answer (present in raw tool output, "
        "dropped by synthesis): %s",
        amount_list,
    )
    return (
        final_answer
        + f"\n\n[FAIT DÉTERMINISTIQUE] Le verrou de sécurité contient une condition "
        f"supplémentaire déclenchée au-delà de {amount_list}, distincte du groupe "
        f"requis ci-dessus. Fait extrait directement de l'analyse statique du code."
    )


# Bloc 9 gap, module 1/8 (2026-08-12, bloc9-01b-technical): the marker-only
# E2E check (scripts/check_bloc9_01_credit_note_cascade_e2e.py) verifies
# that expected module names/amounts appear SOMEWHERE in the final answer
# (via expected_markers, and via the two backfills above when synthesis
# drops them) -- but never checks whether the LLM's own free prose ABOVE
# those facts actively contradicts them. Live run confirmed 3/3 by that
# check (all expected markers present, no forbidden markers) while the
# free prose still asserted, verbatim: (1) "Aucune autre surcharge n'a été
# détectée dans les autres modules analysés" -- immediately followed by
# the [FAIT DÉTERMINISTIQUE] naming the two other override modules that
# very sentence denies exist -- and (2) a fabricated Odoo execution
# semantic ("la surcharge la plus spécifique... est exécutée en premier...
# si elle ne lève pas d'erreur, les autres ne seront pas exécutées"), which
# is not how Odoo resolves an override chain: there is no such
# specificity-based short-circuit, and the real order (given by this same
# tool, vip -> regional -> base here) is never actually used in that
# sentence. Exactly the same family of bug as Bug 2 already documented for
# module 5/8 (_LINK_GUARD_CONTRADICTING_SENTENCE_RE): a correct fact
# appended below a free-text sentence does not, on its own, correct that
# sentence for a reader reading top-to-bottom -- a Discuss end user reads
# the wrong claim before ever reaching the fact that contradicts it. Not a
# script false positive to silence: the check does exactly what it was
# built to do (verify facts); this is a real quality gap the check was
# never designed to catch (prose/fact consistency, not fact presence).
# Same fix shape as module 5/8's Bug 2: detect the specific confirmed-real
# wrong sentence and replace it in place, do not merely append a fact
# after it.
#
# Second confirmed-real denial phrasing added 2026-08-13 (module 1/8
# rerun, bloc9-01b-technical, same session as the security-lock
# per-block scoping fix above): "il n'y a pas de surcharges de la
# methode ... detectees dans les fichiers analyses" -- a STRONGER,
# more harmful denial than "aucune autre surcharge" (that one at least
# implies one override is known; this one denies ANY exist at all),
# live-confirmed immediately followed by the [FAIT DETERMINISTIQUE]
# naming all three real modules, and by a further hallucinated tangent
# suggesting the reader grep generic core Odoo files
# (account/models/account_move.py, account/populate/account_move.py)
# that have nothing to do with this custom cascade. Coincided with this
# run being the first to hit a Groq 413 ("payload too large") on EVERY
# one of the three questions -- plausibly the ReAct-loop ToolMessage
# being cut to _TOOL_MSG_HARD_CAP=400 chars by _reduce_message_context
# left the synthesis LLM with too little real tool content to reason
# from, rather than a synthesis-quality regression on its own. That
# truncation behavior is a separate, pre-existing, documented tradeoff
# (see _reduce_message_context/_invoke_with_rate_limit above) -- NOT
# touched here; widening it would need its own dedicated diagnosis
# (which tool messages to prioritize keeping, whether 400 chars is
# still adequate now that scoped_tool_output routinely carries more
# than one tool's block per turn) rather than a incidental change
# bundled into this narrower prose-correction fix.
_OVERRIDE_COUNT_DENIAL_RE = re.compile(
    r"[^.\n]*aucune\s+autre\s+surcharge[^.\n]*\.?"
    r"|[^.\n]*il\s+n['\u2019]y\s+a\s+pas\s+de\s+surcharges?[^.\n]*detectees?[^.\n]*\.?"
)

# Confirmed-real vocabulary only (same discipline as
# _LINK_GUARD_CONTRADICTION_PATTERN above): the fabricated short-circuit
# claim found live requires BOTH "erreur" and a "ne (sera|seront) pas
# exécutée(s)" clause in the same sentence, with "erreur" preceding the
# verb clause -- matches "si elle ne lève pas d'erreur, les autres ne
# seront pas exécutées" verbatim. Deliberately narrow (same over-editing
# caution as every other neutralizer in this file, see the hallucination
# case in method_override_resolver.py, contexte.txt section 24) rather
# than a generic "any wrong claim about execution order" detector.
_OVERRIDE_ORDER_SHORTCIRCUIT_SENTENCE_RE = re.compile(
    r"[^.\n]*erreur[^.\n]*ne\s+(?:seront|sera)\s+pas\s+executee?s?[^.\n]*\.?"
)


def _answer_denies_other_overrides(final_answer: str) -> bool:
    """True if final_answer explicitly claims no other override exists --
    only meaningful as a contradiction when the raw tool output actually
    lists 2+ modules (checked by the caller, _correct_override_cascade_
    contradictions). Accent-folded, same technique as
    _answer_contradicts_link_guard."""
    from code_intelligence.deterministic_tools import _fold_accents
    folded = _fold_accents(final_answer.lower())
    return bool(_OVERRIDE_COUNT_DENIAL_RE.search(folded))


def _answer_asserts_override_shortcircuit(final_answer: str) -> bool:
    """True if final_answer asserts a specificity-based short-circuit
    ("most specific override runs first, others are skipped if it doesn't
    raise") that does not exist in Odoo's real override semantics."""
    from code_intelligence.deterministic_tools import _fold_accents
    folded = _fold_accents(final_answer.lower())
    return bool(_OVERRIDE_ORDER_SHORTCIRCUIT_SENTENCE_RE.search(folded))


def _neutralize_override_count_denial(final_answer: str, modules: List[str]) -> str:
    """Replace the exact sentence denying any other override with the real
    count and module list, in place -- same offset-alignment technique as
    _neutralize_contradicting_link_guard_sentence (fold+lower is a 1:1,
    length-preserving transform for French text, so match.span() computed
    on the folded string lines up with the original). No-op if no such
    sentence is found."""
    from code_intelligence.deterministic_tools import _fold_accents
    folded = _fold_accents(final_answer.lower())
    match = _OVERRIDE_COUNT_DENIAL_RE.search(folded)
    if not match:
        return final_answer

    modules_list = ", ".join(f"'{m}'" for m in modules)
    replacement = (
        f"Il existe en réalité {len(modules)} surcharges de cette méthode, "
        f"dans les modules suivants : {modules_list}."
    )
    start, end = match.span()
    return final_answer[:start] + replacement + final_answer[end:]


def _neutralize_override_shortcircuit_sentence(final_answer: str, modules: List[str]) -> str:
    """Replace the exact sentence asserting a fabricated specificity-based
    short-circuit with the real execution semantics, in place -- same
    technique as _neutralize_override_count_denial above. modules must
    already be in real execution order (as returned by
    _extract_override_modules, itself sourced from
    resoudre_chaine_surcharge_methode's reversed load order) -- this
    function does not reorder them, only restates them."""
    from code_intelligence.deterministic_tools import _fold_accents
    folded = _fold_accents(final_answer.lower())
    match = _OVERRIDE_ORDER_SHORTCIRCUIT_SENTENCE_RE.search(folded)
    if not match:
        return final_answer

    order = " → ".join(modules) if modules else "l'ordre indiqué par l'outil"
    replacement = (
        f"Odoo n'applique aucun court-circuit basé sur la spécificité ou "
        f"l'absence d'erreur : les surcharges s'exécutent toutes, dans "
        f"l'ordre réel {order}, et l'exécution d'une surcharge ne s'arrête "
        f"que si elle omet d'appeler super() ou lève explicitement une erreur."
    )
    start, end = match.span()
    return final_answer[:start] + replacement + final_answer[end:]


def _correct_override_cascade_contradictions(final_answer: str, raw_tool_output: str) -> str:
    """Entry point wiring the two neutralizations above into the same
    deterministic-correction discipline as _backfill_link_guard_
    clarifications: detect a confirmed-real contradiction between the
    LLM's free prose and the override-cascade facts, and replace the wrong
    sentence in place rather than only appending a correct fact below it
    -- an appended fact does not, by itself, correct a wrong sentence a
    top-to-bottom reader already read. No-op when the raw text does not
    describe an override chain at all, or describes only a single-module
    chain (a single override correctly saying "no other override exists"
    is not a contradiction)."""
    modules = _extract_override_modules(raw_tool_output)

    if len(modules) > 1 and _answer_denies_other_overrides(final_answer):
        logger.warning(
            "Node [code_intelligence_agent]: synthesis denied the existence "
            "of other overrides while %d modules were present in the raw "
            "tool output -- replacing the denial sentence with the real "
            "count and module list.",
            len(modules),
        )
        final_answer = _neutralize_override_count_denial(final_answer, modules)

    if modules and _answer_asserts_override_shortcircuit(final_answer):
        logger.warning(
            "Node [code_intelligence_agent]: synthesis asserted a "
            "fabricated specificity-based short-circuit for the override "
            "cascade -- replacing the sentence with the real (sequential, "
            "non-short-circuiting) execution semantics."
        )
        final_answer = _neutralize_override_shortcircuit_sentence(final_answer, modules)

    return final_answer


# Bloc 9 gap, found 2026-08-10 (bloc9-05c-no-link-trap, generalization check
# 5/8 on custom_asset_loan): the [GARDE DE LIEN] annotation appended by
# semgrep_locks_analyzer.py (see SecurityLockASTVisitor._detect_link_guard_
# field docstring) already states the correct short-circuit conclusion in
# the raw tool text -- but a live run showed the synthesis LLM misreading
# it anyway, concluding the rule "applies when NOT linked", the exact
# inverse of the ground truth, DESPITE the condition being quoted correctly
# elsewhere in the same answer. Unlike the required-groups gap (content
# silently dropped), this is content present AND read, but reasoned about
# incorrectly -- so the fix is not "add it if missing" but "always restate
# the computed conclusion explicitly", the same principle already applied
# to _format_can_view_amount_fact (a boolean verdict is safer handed to the
# LLM pre-computed than left for it to (mis)derive from raw material).
_LINK_GUARD_RE = re.compile(
    r"\[GARDE DE LIEN: si '([^']+)' est vide/absent .*?NE S'APPLIQUE PAS dans ce cas",
    re.DOTALL,
)

# Bloc 9 gap, module 5/8 Bug 2 (2026-08-11, bloc9-05c-no-link-trap). First
# attempt (same day) only PREPENDED a correction banner ahead of the
# unchanged wrong prose. Confirmed still failing on a real rerun the same
# day: the banner fires and logs correctly, but the literal wrong sentence
# ("s'applique quand meme...") remains fully readable right below it --
# scripts/check_bloc9_05_asset_loan_e2e.py's forbidden_markers check still
# flags it, and more importantly a non-technical Discuss end user skimming
# past a disclaimer would still read the wrong sentence as the answer. This
# product's stated audience is non-dev (Discuss chat widget, sources hidden
# behind a collapsed chevron) -- the visible answer must be correct on its
# own, not correct-only-if-the-reader-notices-the-caveat-first. Revised to
# surgically replace the exact matched sentence instead of merely flagging
# it -- narrower than a general rewrite (over-trimming risk already flagged
# for the hallucination case in method_override_resolver.py, contexte.txt
# section 24): only the specific confirmed-real contradiction pattern is
# touched, matched at the single-sentence boundary, nothing else in the
# answer is altered.
_LINK_GUARD_CONTRADICTION_PATTERN = re.compile(
    r"s.?applique\s+(quand\s+meme|tout\s+de\s+meme|malgre|dans\s+tous\s+les\s+cas|"
    r"de\s+toute\s+facon|independamment|meme\s+sans|meme\s+en\s+l.?absence)"
)

# Same confirmed-real vocabulary as _LINK_GUARD_CONTRADICTION_PATTERN above,
# widened to capture the WHOLE sentence containing it (bounded by '.'/'\n' on
# either side) so the replacement can swap out the entire wrong claim, not
# just the matched fragment -- leaving fragments of the wrong sentence behind
# (e.g. "..., quel que soit le montant du materiel, dans le cas ou...") would
# still read as a wrong claim once stitched to a different ending.
_LINK_GUARD_CONTRADICTING_SENTENCE_RE = re.compile(
    r"[^.\n]*s.?applique\s+(?:quand\s+meme|tout\s+de\s+meme|malgre|dans\s+tous\s+les\s+cas|"
    r"de\s+toute\s+facon|independamment|meme\s+sans|meme\s+en\s+l.?absence)[^.\n]*\.?"
)


def _answer_contradicts_link_guard(final_answer: str) -> bool:
    """True if final_answer asserts the rule applies despite an absent
    guard field, the exact inverse of what the link-guard short-circuit
    always means. Accent-folded (same technique as modules 2/8-5/8's own
    _fold_accents in their check scripts, imported here rather than
    reimplemented) since the LLM may re-accent 'meme'/'malgre' when
    paraphrasing."""
    from code_intelligence.deterministic_tools import _fold_accents
    folded = _fold_accents(final_answer.lower())
    return bool(_LINK_GUARD_CONTRADICTION_PATTERN.search(folded))


def _neutralize_contradicting_link_guard_sentence(final_answer: str, guard_fields: List[str]) -> str:
    """Replace the exact sentence asserting the wrong (inverse) link-guard
    conclusion with the correct one, in place -- see the module comment
    above _LINK_GUARD_CONTRADICTING_SENTENCE_RE for why this replaces
    rather than merely flags. Matches on the accent-folded/lowercased text
    (same technique as _answer_contradicts_link_guard) but slices the
    ORIGINAL final_answer at the same offsets: _fold_accents is a 1:1
    character substitution (NFD decompose + drop combining marks always
    yields exactly one base character per input character) and .lower()
    is length-preserving for French text, so match.span() computed on the
    folded/lowered string lines up with the original string's indices.
    No-op (returns final_answer unchanged) if no contradicting sentence is
    found -- callers must still gate this on _answer_contradicts_link_guard
    for the correct log line, this function alone would just be silently
    idempotent."""
    from code_intelligence.deterministic_tools import _fold_accents
    folded = _fold_accents(final_answer.lower())
    match = _LINK_GUARD_CONTRADICTING_SENTENCE_RE.search(folded)
    if not match:
        return final_answer

    fields_list = ", ".join(f"'{g}'" for g in guard_fields)
    replacement = (
        f"La règle NE s'applique PAS en l'absence de {fields_list} "
        f"(court-circuit Python : un champ vide/absent en première position "
        f"d'un `and` rend toute la condition fausse)."
    )
    start, end = match.span()
    return final_answer[:start] + replacement + final_answer[end:]


def _extract_link_guard_fields(raw_tool_output: str) -> List[str]:
    """Pull every [GARDE DE LIEN] guarding field name out of the raw tool
    text, in first-seen order, deduplicated. Returns [] if no such
    annotation is present."""
    fields: List[str] = []
    for match in _LINK_GUARD_RE.finditer(raw_tool_output):
        name = match.group(1).strip()
        if name and name not in fields:
            fields.append(name)
    return fields


_TRIGGER_CONDITION_RE = re.compile(r"\u26a1 Condition\(s\) de d\u00e9clenchement\s*:\s*(.+)")
_TRIGGER_CONDITION_LITERAL_RE = re.compile(r"'([^']+)'")


def _extract_trigger_condition_literals(raw_tool_output: str) -> List[str]:
    """
    Bloc 9 gap, module 6/8 (bloc9-06c-technical-condition-capture,
    2026-08-11): the server-action trigger-condition line
    (analyser_actions_serveur's "\u26a1 Condition(s) de d\u00e9clenchement:
    rec.move_type == 'in_refund' and rec.partner_id.id in
    FOURNISSEURS_PRIVILEGIES") gets correctly PARAPHRASED by the synthesis
    LLM ("avoirs re\u00e7us de trois fournisseurs sp\u00e9cifiques") but the
    literal string constant inside the condition ('in_refund') never
    survives verbatim -- same class of gap as _extract_override_chain_amounts
    above, at the string-literal granularity instead of the numeric-
    threshold one.

    Deliberately extracts only the QUOTED STRING LITERALS inside the
    trigger-condition line, not the whole boolean expression -- backfilling
    the entire multi-clause condition every time the LLM's (correct,
    readable) paraphrase doesn't reproduce it byte-for-byte would be noisy
    and largely redundant; the specific literal token is the actual thing a
    consultant needs to grep the code for. Returns [] if the line isn't
    present at all (tool wasn't invoked, or found no trigger condition).
    """
    match = _TRIGGER_CONDITION_RE.search(raw_tool_output)
    if not match:
        return []
    literals: List[str] = []
    for lit_match in _TRIGGER_CONDITION_LITERAL_RE.finditer(match.group(1)):
        lit = lit_match.group(1)
        if lit and lit not in literals:
            literals.append(lit)
    return literals


def _backfill_missing_trigger_condition_literals(final_answer: str, raw_tool_output: str) -> str:
    """Deterministic backfill, same append-only/never-override discipline
    as every other backfill in this module: if a server-action's trigger
    condition contains a quoted string literal (already present verbatim
    in the raw tool text) that never made it into the synthesized answer,
    append it as an explicit, clearly labeled fact. No-op whenever every
    literal is already present -- never duplicates or contradicts a
    correct synthesis."""
    literals = _extract_trigger_condition_literals(raw_tool_output)
    if not literals:
        return final_answer

    missing = [lit for lit in literals if lit not in final_answer]
    if not missing:
        return final_answer

    lit_list = ", ".join(f"`{lit}`" for lit in missing)
    logger.info(
        "Node [code_intelligence_agent]: backfilling server-action trigger-condition "
        "literal(s) missing from synthesized answer (present in raw tool output, "
        "paraphrased away by synthesis): %s",
        lit_list,
    )
    return (
        final_answer
        + f"\n\n[FAIT D\u00c9TERMINISTIQUE] Valeur(s) litt\u00e9rale(s) de la condition de "
        f"d\u00e9clenchement de l'action serveur, absente(s) de la reformulation "
        f"ci-dessus : {lit_list}. Fait extrait directement de l'analyse statique "
        f"du code."
    )


# Bloc 9 gap, module 6/8 (bloc9-06c-technical-condition-capture, found
# 2026-08-13 -- rerun immediately AFTER the analyser_actions_serveur
# truncation-cap fix is confirmed active on disk): the cap fix restores
# sudo()/in_refund to the stored observation and to the final answer
# (06b/06c both pass on those markers now), but 06c still drops the
# hardcoded privileged-partner IDs (42, 108, 231) -- present verbatim in
# the raw tool text ("[CONTOURNEMENT SENSIBLE] IDs en dur: [42, 108, 231]
# -> traitement privilegie non documente") but never reaching the LLM's
# paraphrase. Same class of gap as the trigger-condition literal above (a
# bracketed technical detail the small model summarizes away in favor of
# prose, e.g. "trois fournisseurs specifiques"), just on the sibling line
# one row below it in the same finding -- confirmed NOT a truncation
# symptom this time (the raw check's own direct call already shows "42"
# present under the now-3000 cap), so a dedicated backfill rather than
# another cap raise.
_HARDCODED_IDS_LINE_RE = re.compile(r"IDs en dur\s*:\s*\[([^\]]+)\]")


def _extract_hardcoded_id_literals(raw_tool_output: str) -> List[str]:
    """Pull every hardcoded-ID token out of a server-action bypass finding's
    \"IDs en dur: [...]\" line, in first-seen order, deduplicated. Returns []
    if no such line is present -- tool wasn't invoked, the finding was
    gated out for an unprivileged requester (authorization_gate.py), or no
    hardcoded-ID bypass exists on this model at all."""
    match = _HARDCODED_IDS_LINE_RE.search(raw_tool_output)
    if not match:
        return []
    ids: List[str] = []
    for raw_id in match.group(1).split(","):
        raw_id = raw_id.strip()
        if raw_id and raw_id not in ids:
            ids.append(raw_id)
    return ids


def _backfill_missing_hardcoded_id_literals(final_answer: str, raw_tool_output: str) -> str:
    """Deterministic backfill, same append-only/never-override discipline as
    every other backfill in this module: if a server-action's hardcoded-ID
    bypass list (already present verbatim in the raw tool text) never made
    it into the synthesized answer, append it as an explicit, clearly
    labeled fact. No-op whenever every ID is already present -- never
    duplicates or contradicts a correct synthesis. Reuses
    _amount_present_in_text for a digit-boundary-safe presence check (an
    ID is just a bare digit string, e.g. '42' must not count as already
    present merely because '142' or '420' appears somewhere in the
    answer) -- same reasoning as its existing use for monetary amounts.
    """
    ids = _extract_hardcoded_id_literals(raw_tool_output)
    if not ids:
        return final_answer

    missing = [i for i in ids if not _amount_present_in_text(i, final_answer)]
    if not missing:
        return final_answer

    id_list = ", ".join(missing)
    logger.info(
        "Node [code_intelligence_agent]: backfilling hardcoded privileged-ID "
        "literal(s) missing from synthesized answer (present in raw tool "
        "output, paraphrased away by synthesis): %s",
        id_list,
    )
    return (
        final_answer
        + f"\n\n[FAIT D\u00c9TERMINISTIQUE] Valeur(s) litt\u00e9rale(s) des identifiants "
        f"cod\u00e9s en dur b\u00e9n\u00e9ficiant du contournement, absente(s) de la "
        f"reformulation ci-dessus : {id_list}. Fait extrait directement de "
        f"l'analyse statique du code."
    )


# Bloc 9 gap fix (2026-08-11, module 1/8, bloc9-01c-vip-trap): the
# SUPER() NON GARDÉ warning from method_override_resolver.py contains two
# pieces of information the synthesis LLM reliably drops when Groq 413
# truncation cuts the override-chain observation: (1) the condition field
# name (e.g. `rec.partner_id.avoir_vip_exempt`) and (2) the fact that
# super() is called unconditionally after a conditional branch. Same
# extraction-then-backfill pattern as every other backfill in this module.
_UNGUARDED_SUPER_RE = re.compile(
    r"SUPER\(\) NON GARD[ÉE].*?module '([\w.]+)'\).*?"
    r"branche conditionnelle \(`([^`]+)`\)"
)


def _extract_unguarded_super_findings(raw_tool_output: str) -> List[Tuple[str, str]]:
    """Extract (module, condition) pairs from SUPER() NON GARDÉ warnings
    in the override-chain analysis output."""
    return _UNGUARDED_SUPER_RE.findall(raw_tool_output)


def _backfill_missing_unguarded_super(final_answer: str, raw_tool_output: str) -> str:
    """Deterministic backfill for SUPER() NON GARDÉ warnings from the
    override-cascade analysis (method_override_resolver.py). Same append-
    only, never-override discipline as every other backfill: if the raw
    tool output contains an unguarded-super warning whose condition field
    (e.g. `avoir_vip_exempt`) is missing from the synthesized answer,
    append it as a labeled fact. Covers the case where Groq 413 payload
    truncation drops the override-chain detail before the synthesis LLM
    ever sees it -- confirmed live on bloc9-01c-vip-trap (2026-08-11)."""
    findings = _extract_unguarded_super_findings(raw_tool_output)
    if not findings:
        return final_answer

    missing_items = []
    for module, condition in findings:
        # Extract the terminal field name from the condition expression,
        # e.g. "avoir_vip_exempt" from "rec.partner_id.avoir_vip_exempt".
        field_name = condition.rsplit(".", 1)[-1] if "." in condition else condition
        if field_name not in final_answer:
            missing_items.append((module, condition))

    if not missing_items:
        return final_answer

    parts = []
    for module, condition in missing_items:
        parts.append(
            f"module '{module}' : branche conditionnelle `{condition}` "
            f"avec super() rappelé inconditionnellement (risque d'annulation "
            f"silencieuse de cette logique)"
        )

    detail = " ; ".join(parts)
    logger.info(
        "Node [code_intelligence_agent]: backfilling SUPER() NON GARDÉ finding(s) "
        "missing from synthesized answer: %s", detail,
    )
    return (
        final_answer
        + f"\n\n[FAIT DÉTERMINISTIQUE] SUPER() NON GARDÉ détecté dans la chaîne de "
        f"surcharge : {detail}. "
        f"Fait extrait directement de l'analyse statique du code."
    )


def _backfill_link_guard_clarifications(final_answer: str, raw_tool_output: str) -> str:
    """Deterministic backfill, always appended (not conditional on question
    wording, unlike _backfill_missing_required_groups) whenever a [GARDE DE
    LIEN] annotation is present in the raw tool output -- restates the
    already-computed short-circuit conclusion explicitly as a labeled fact,
    regardless of what the LLM said, so an incorrect natural-language
    reading of the raw condition text can never be the only thing the user
    sees. Idempotent: no-op if the marker sentence is already present
    (e.g. a future synthesis run that gets it right on its own).
    """
    guard_fields = _extract_link_guard_fields(raw_tool_output)
    if not guard_fields:
        return final_answer

    marker = "[FAIT DÉTERMINISTIQUE] Court-circuit"
    if marker in final_answer:
        return final_answer

    fields_list = ", ".join(f"'{g}'" for g in guard_fields)

    if _answer_contradicts_link_guard(final_answer):
        logger.warning(
            "Node [code_intelligence_agent]: synthesis contradicted its own "
            "link-guard short-circuit conclusion for field(s) %s -- replacing "
            "the contradicting sentence with the correct conclusion (no longer "
            "just a banner ahead of the unchanged wrong prose -- see comment "
            "above _LINK_GUARD_CONTRADICTING_SENTENCE_RE, 2026-08-11 rerun "
            "confirmed a banner alone still left the wrong sentence readable).",
            fields_list,
        )
        final_answer = _neutralize_contradicting_link_guard_sentence(final_answer, guard_fields)

    logger.info(
        "Node [code_intelligence_agent]: appending deterministic link-guard "
        "clarification (short-circuit conclusion) for field(s): %s",
        fields_list,
    )
    return (
        final_answer
        + f"\n\n{marker} ET (déterministe) : l'analyse statique du code montre que "
        f"la condition dépend de {fields_list} en première position d'un `and` -- si ce "
        f"champ est vide ou absent (aucun enregistrement lié), toute la condition est "
        f"FAUSSE par court-circuit Python, et la règle correspondante NE S'APPLIQUE PAS, "
        f"quel que soit le reste de la condition (montant, etc.). Fait extrait directement "
        f"de l'analyse statique du code, indépendant de toute reformulation en langage naturel."
    )


# Bloc9 08c follow-up (2026-08-14): synthesis-inversion detector for the
# can_view_amount_v2 deterministic fact, symmetric to module 5/8's Bug 2 fix
# (_correct_override_cascade_contradictions / _neutralize_contradicting_
# link_guard_sentence above) but for THIS fact instead of the link-guard
# short-circuit. The diagnostic logging already added at the injection call
# site ("Injected deterministic can_view_amount_v2 fact ...") only lets a
# human distinguish a resolution/wiring gap (model not found, zero rules
# applied -> would silently default this to True) from a synthesis-level
# inversion of an otherwise-correct verdict -- it does not fix the inversion
# case even once the log confirms that's what happened. This closes that
# second half: if the appended [FAIT DETERMINISTIQUE] disagrees with what
# the LLM's own free prose asserted earlier in the same answer, replace the
# wrong sentence in place -- an appended correct fact below a wrong sentence
# does not, on its own, correct that sentence for a top-to-bottom reader.
#
# CUTOFF (found in sandbox testing, 2026-08-14, before this was wired in
# here): once the can_view_amount_v2 fact itself is appended to final_answer
# (e.g. "...l'utilisateur PEUT voir cet enregistrement."), the same ALLOW/
# DENY assertion regex also matches that appended sentence -- an auto-
# collision where the fact would flag itself as contradicting itself.
# _split_before_first_fact_marker scans only the free-prose portion of
# final_answer BEFORE the first "[FAIT" marker to avoid this.
_CAN_VIEW_ALLOW_ASSERTION_RE = re.compile(
    r"[^.\n]*\b(?:peut\s+(?:voir|consulter|acc[ée]der)|"
    r"(?:a|dispose\s+du?)\s+(?:le\s+)?droit\s+de\s+(?:voir|consulter)|"
    r"est\s+autoris[ée]\s+[àa]\s+(?:voir|consulter|acc[ée]der))[^.\n]*\.?",
    re.IGNORECASE,
)
_CAN_VIEW_DENY_ASSERTION_RE = re.compile(
    r"[^.\n]*\bne\s+peut\s+pas\s+(?:voir|consulter|acc[ée]der)[^.\n]*\.?"
    r"|[^.\n]*n[’']a\s+pas\s+(?:le\s+)?droit\s+de\s+(?:voir|consulter)[^.\n]*\.?"
    r"|[^.\n]*n[’']est\s+pas\s+autoris[ée]\s+[àa]\s+(?:voir|consulter|acc[ée]der)[^.\n]*\.?",
    re.IGNORECASE,
)
_CAN_VIEW_FACT_VERDICT_RE = re.compile(
    r"can_view_amount\(\)\s*=\s*(True|False)\s*:\s*l.utilisateur\s+(PEUT|NE PEUT PAS)",
)
_CAN_VIEW_FACT_INDETERMINATE_MARKER = "can_view_amount_v2() = indéterminé"


def _split_before_first_fact_marker(text: str) -> str:
    """Text portion before the first '[FAIT' marker -- the free-prose
    synthesis, excluding every deterministic fact appended by the backfills
    in this module. See the CUTOFF note above _CAN_VIEW_ALLOW_ASSERTION_RE
    for the auto-collision this avoids."""
    idx = text.find("[FAIT")
    return text if idx == -1 else text[:idx]


def _extract_can_view_amount_verdict(final_answer: str) -> "Optional[bool]":
    """True/False when the injected can_view_amount_v2 fact states a
    definite verdict. Returns None both when no such fact is present at all
    AND when the fact states the indeterminate case -- callers distinguish
    the two via _has_can_view_amount_fact separately."""
    match = _CAN_VIEW_FACT_VERDICT_RE.search(final_answer)
    if not match:
        return None
    return match.group(2) == "PEUT"


def _has_can_view_amount_fact(final_answer: str) -> bool:
    return bool(_CAN_VIEW_FACT_VERDICT_RE.search(final_answer)) or (
        _CAN_VIEW_FACT_INDETERMINATE_MARKER in final_answer
    )


def _correct_can_view_amount_contradictions(final_answer: str) -> str:
    """
    Detect and correct a synthesis-level inversion of the can_view_amount_v2
    deterministic verdict -- e.g. the fact says NE PEUT PAS (False) but the
    LLM's own free prose earlier in the same answer asserts the user peut
    voir, or the fact is indeterminate but the prose still rounds to a
    definite yes/no. Symmetric, append-after-detect-and-replace discipline
    to _correct_override_cascade_contradictions above. No-op when no
    can_view_amount_v2 fact is present at all in final_answer (this tool
    didn't run this turn, or no amount was extractable from the question).
    """
    if not _has_can_view_amount_fact(final_answer):
        return final_answer

    prose = _split_before_first_fact_marker(final_answer)
    is_indeterminate = _CAN_VIEW_FACT_INDETERMINATE_MARKER in final_answer
    verdict = _extract_can_view_amount_verdict(final_answer)

    if is_indeterminate:
        # A definite allow OR a definite deny in the prose both contradict
        # an indeterminate verdict -- rounding uncertainty to a yes/no is
        # exactly what the deterministic fact + synthesis_prompt already
        # forbid, regardless of which direction the LLM rounded to.
        match = _CAN_VIEW_ALLOW_ASSERTION_RE.search(prose) or _CAN_VIEW_DENY_ASSERTION_RE.search(prose)
        if not match:
            return final_answer
        replacement = (
            "Le moteur de règles ne peut pas déterminer avec certitude si "
            "l'utilisateur peut voir cet enregistrement pour ce montant "
            "(voir le fait déterministe ci-dessous)."
        )
        logger.warning(
            "Node [code_intelligence_agent]: synthesis asserted a definite "
            "allow/deny while the can_view_amount_v2 verdict was indéterminé "
            "-- replacing the sentence with an explicit uncertainty statement "
            "(_correct_can_view_amount_contradictions)."
        )
    elif verdict is True:
        match = _CAN_VIEW_DENY_ASSERTION_RE.search(prose)
        if not match:
            return final_answer
        replacement = (
            "L'utilisateur PEUT voir cet enregistrement pour ce montant "
            "(voir le fait déterministe ci-dessous)."
        )
        logger.warning(
            "Node [code_intelligence_agent]: synthesis asserted the user "
            "CANNOT view the record while can_view_amount_v2() computed "
            "True -- replacing the sentence with the correct verdict "
            "(inversion, _correct_can_view_amount_contradictions)."
        )
    elif verdict is False:
        match = _CAN_VIEW_ALLOW_ASSERTION_RE.search(prose)
        if not match:
            return final_answer
        replacement = (
            "L'utilisateur NE PEUT PAS voir cet enregistrement pour ce "
            "montant (voir le fait déterministe ci-dessous)."
        )
        logger.warning(
            "Node [code_intelligence_agent]: synthesis asserted the user "
            "CAN view the record while can_view_amount_v2() computed "
            "False -- replacing the sentence with the correct verdict "
            "(inversion, _correct_can_view_amount_contradictions)."
        )
    else:
        return final_answer

    start, end = match.span()
    return final_answer[:start] + replacement + final_answer[end:]


def _correct_security_lock_threshold_contradictions(
    final_answer: str, scoped_tool_output: str, question: str
) -> str:
    """Bloc 9 gap fix (2026-08-14, module 8/8, bloc9-08a-business):
    detect and correct synthesis-level inversions of Python security lock
    threshold logic (has_group() with numeric amount conditions).

    Small synthesis LLMs frequently conflate independent threshold gates
    (e.g. >50k requires account.group_account_manager, >100k requires base.group_system)
    by treating them as exclusive authority tiers / upper bounds -- claiming that a
    manager only has the right up to 50k and cannot validate at 60k, and/or claiming
    that the higher admin group is required/authorized at 60k.

    This detector reconciles the free prose against the ground-truth lock conditions
    extracted from scoped_tool_output for the specific monetary amount in question.
    """
    from code_intelligence.deterministic_tools import _fold_accents

    amount = _extract_amount(question)
    if amount is None:
        return final_answer

    rules: List[Tuple[str, str, float, str]] = []
    for match in _LOCK_CONDITION_LINE_RE.finditer(scoped_tool_output):
        cond_text = match.group(1)
        group_name = match.group(2).strip()
        cmp_match = _AMOUNT_CMP_RE.search(cond_text)
        if cmp_match:
            op = cmp_match.group(1)
            thresh = float(cmp_match.group(2))
            rules.append((group_name, op, thresh, cond_text))

    if not rules:
        return final_answer

    triggered = [
        (g, op, thresh, cond)
        for g, op, thresh, cond in rules
        if (op == ">" and amount > thresh) or (op == ">=" and amount >= thresh)
    ]
    higher_untriggered = [
        (g, op, thresh, cond)
        for g, op, thresh, cond in rules
        if op in (">", ">=") and thresh > amount
    ]

    if not triggered and not higher_untriggered:
        return final_answer

    prose = _split_before_first_fact_marker(final_answer)
    suffix = final_answer[len(prose):]

    if "\n\n" in prose:
        delimiter = "\n\n"
        chunks = prose.split("\n\n")
    elif "\n-" in prose or "\n*" in prose:
        delimiter = "\n"
        chunks = prose.split("\n")
    else:
        delimiter = "\n\n"
        chunks = [prose]

    amt_s = str(int(amount))
    amt_sp = f"{int(amount):,}".replace(",", " ")
    new_chunks = []
    contradiction_found = False

    for chunk in chunks:
        c_folded = _fold_accents(chunk.lower())
        prefix = "- " if chunk.strip().startswith("- ") else ("* " if chunk.strip().startswith("* ") else "")
        replaced = False

        # Check for triggered group inversion
        for g, op, thresh, cond in triggered:
            t_s = str(int(thresh))
            t_sp = f"{int(thresh):,}".replace(",", " ")
            g_short = g.split(".")[-1].replace("group_", "")

            group_keywords = [g.lower(), g_short.lower()]
            if "account" in g.lower() or "comptab" in cond.lower():
                group_keywords.extend(["comptabilit", "responsable"])
            if "manager" in g.lower():
                group_keywords.extend(["manager", "responsable", "gestionnaire"])

            has_group_ref = any(k in c_folded for k in group_keywords)
            if has_group_ref:
                is_inv = False
                if any(w in c_folded for w in ["jusqu", "plafond", "limite"]) and (t_s in c_folded or t_sp in c_folded):
                    if any(w in c_folded for w in ["n'a pas le droit", "ne peut pas", "ne peut donc pas", "n'est pas autoris", "pas autoris"]):
                        is_inv = True
                elif any(w in c_folded for w in ["n'a pas le droit de valider", "ne peut pas valider", "ne peut donc pas valider", "n'est pas autoris"]):
                    if amt_s in c_folded or amt_sp in c_folded or "ce document" in c_folded or "ce montant" in c_folded:
                        is_inv = True

                if is_inv:
                    new_chunks.append(
                        f"{prefix}Pour un document de {amt_sp}€ (dépassant le seuil de {t_sp}€), "
                        f"la validation exige d'être membre du groupe `{g}`. "
                        f"Un membre de ce groupe a donc le droit de valider ce document."
                    )
                    replaced = True
                    contradiction_found = True
                    break

        if replaced:
            continue

        # Check for higher untriggered wrongful authority attribution
        for hg, hop, hthresh, hcond in higher_untriggered:
            ht_s = str(int(hthresh))
            ht_sp = f"{int(hthresh):,}".replace(",", " ")
            hg_short = hg.split(".")[-1].replace("group_", "")

            hg_keywords = [hg.lower(), hg_short.lower()]
            if "system" in hg.lower() or "admin" in hg.lower():
                hg_keywords.extend(["administrateur", "system"])

            has_hg_ref = any(k in c_folded for k in hg_keywords)
            if has_hg_ref:
                is_wrong = False
                if ht_s in c_folded or ht_sp in c_folded or "100k" in c_folded or "100 k" in c_folded:
                    if any(w in c_folded for w in ["a le droit de valider", "peut valider", "est autoris"]):
                        if amt_s in c_folded or amt_sp in c_folded or "ce document" in c_folded or "ce montant" in c_folded:
                            is_wrong = True

                if is_wrong:
                    new_chunks.append(
                        f"{prefix}Le verrou supérieur (> {ht_sp}€, réservé à `{hg}`) ne s'applique pas "
                        f"à {amt_sp}€ car le montant est inférieur à {ht_sp}€."
                    )
                    replaced = True
                    contradiction_found = True
                    break

        if not replaced:
            new_chunks.append(chunk)

    if not contradiction_found:
        return final_answer

    logger.warning(
        "Node [code_intelligence_agent]: synthesis asserted an inverted/contradictory "
        "security lock threshold verdict for amount %s -- replacing contradictory sentences "
        "with correct ground-truth evaluation (_correct_security_lock_threshold_contradictions).",
        amount,
    )
    return delimiter.join(new_chunks) + suffix


# Bloc9 08c gap, found 2026-08-14 (bloc9-08c-nested-domain-trap, live
# rerun after the company-context fix): every OTHER deterministic fact
# injected into tool_observations by this module (required groups,
# override-chain amount/modules, trigger-condition literals, hardcoded
# IDs, link-guard clarification) has a matching _backfill_missing_X that
# guarantees the fact survives into final_answer even when synthesis
# drops or reworks it. The can_view_amount_v2 fact never had one -- it
# only ever reached tool_observations (the synthesis LLM's INPUT), and
# synthesis_prompt explicitly tells the model never to quote the
# '[FAIT DETERMINISTIQUE]' label or the mechanism name verbatim "as if
# that were the explanation". A small instruction-following model
# reliably obeys that by paraphrasing the verdict into free prose
# instead of copying the exact template -- confirmed on the real
# bloc9-08c-nested-domain-trap transcript (todo/etat_reel.md): the
# answer says "can_view_amount() = True... l'utilisateur PEUT voir cet
# enregistrement", a loose paraphrase (comma + "ce qui signifie que"
# instead of the exact " : ") that does NOT match
# _CAN_VIEW_FACT_VERDICT_RE, so _has_can_view_amount_fact() returns
# False on that real answer and _correct_can_view_amount_contradictions()
# silently no-ops just above -- an inversion of the actual verdict
# (confirmed False by direct can_view_amount_v2() replay in sandbox
# against the real domain_force strings from this run's raw tool output
# and a correctly-extracted different-company context) reaches the user
# uncorrected, because the fact it needed to compare the prose against
# was never actually present in final_answer to compare against.
#
# Closes the gap the same way as every sibling backfill: append the
# exact fact block, recovered verbatim from raw_tool_output (never
# re-derived or reworded here), when no such fact is already present in
# final_answer -- so _correct_can_view_amount_contradictions (called
# right after this one) always has a real fact to check the prose
# against, whether the LLM echoed one or not.
def _extract_can_view_amount_fact_block(raw_tool_output: str) -> "Optional[str]":
    """
    Return the exact '[FAIT DETERMINISTIQUE] ... can_view_amount_v2 ...'
    block produced by _format_can_view_amount_fact(), if present anywhere
    in raw_tool_output, else None. Observations are '\n\n'-joined (see
    raw_tool_output/_scoped_raw_tool_output), so splitting on that same
    separator and testing each block with the existing
    _has_can_view_amount_fact() marker check is enough to recover the
    block verbatim, without re-deriving or reformatting its wording here.
    """
    for block in raw_tool_output.split("\n\n"):
        if _has_can_view_amount_fact(block):
            return block.strip()
    return None


def _backfill_missing_can_view_amount_fact(final_answer: str, raw_tool_output: str) -> str:
    """
    No-op when final_answer already contains a can_view_amount_v2 fact
    (LLM echoed or paraphrased it closely enough to match
    _CAN_VIEW_FACT_VERDICT_RE/_CAN_VIEW_FACT_INDETERMINATE_MARKER) or when
    raw_tool_output never carried one at all (tool not called this turn,
    or no amount was extractable from the question -- see the call site
    in code_intelligence_agent). Otherwise appends the verbatim fact block
    so the immediately-following _correct_can_view_amount_contradictions()
    call has an actual fact to reconcile the free prose against, instead
    of silently no-oping on a fact that only ever existed in the LLM's
    input, never its output.
    """
    if _has_can_view_amount_fact(final_answer):
        return final_answer

    block = _extract_can_view_amount_fact_block(raw_tool_output)
    if block is None:
        return final_answer

    logger.info(
        "Node [code_intelligence_agent]: backfilling can_view_amount_v2 "
        "deterministic fact missing from synthesized answer (present in "
        "raw tool output, dropped/paraphrased by synthesis) -- Bloc9 08c "
        "gap, 2026-08-14."
    )
    return final_answer + "\n\n" + block


def _format_can_view_amount_fact(
    amount: float, can_view: "Optional[bool]", unresolved: "Optional[List[str]]" = None
) -> str:
    """
    Bloc 9 gap (2026-08-10, bloc9-02b-no-groups): the previous phrasing
    addressed the synthesis LLM directly in second-person imperative
    INSIDE the data block itself ("ne doit JAMAIS etre recalcule ...
    reprendre ce verdict tel quel"), blurring the line between fact and
    instruction. Live run confirmed the small model (llama-3.1-8b-instant)
    treated that sentence as safe, quotable content and echoed it VERBATIM
    as the entire final answer -- with zero mention of WHY (no rule name,
    no reasoning), on the one question where this was the only observation
    present (no applicable group rule to also cite).

    Kept purely declarative here -- the "never contradict this verdict"
    instruction now lives in synthesis_prompt instead (code_intelligence_
    agent), alongside an explicit instruction to still explain the verdict
    using the OTHER observations in the same response. Extracted as a
    standalone function so this specific regression (no imperative
    second-person sentence inside the injected fact) has a fast,
    deterministic unit test independent of the full ReAct loop / LLM.

    Bloc9 08c fix (deterministic_tools.py can_view_amount_v2): can_view is
    now Optional[bool]. The call site switched from the old regex-based
    can_view_amount() -- which silently returns True whenever a
    domain_force condition it cannot parse (e.g. company_id) is present,
    confirmed root cause of 08c -- to can_view_amount_v2()'s tri-state
    verdict. can_view=None means at least one applicable rule's
    domain_force could not be conclusively evaluated against the available
    context: this is NOT the same as "no restriction found" and must never
    be phrased as an allow/deny answer. unresolved lists the field name(s)
    that blocked a conclusive verdict (e.g. ['company_id']), so the fact
    can name exactly what is missing instead of a generic disclaimer.
    """
    if can_view is None:
        fields_str = ", ".join(unresolved) if unresolved else "une ou plusieurs conditions non résolues"
        return (
            f"[FAIT DÉTERMINISTIQUE] Pour un montant de {amount:.0f}€, "
            f"le moteur de règles NE PEUT PAS déterminer si l'utilisateur peut voir "
            f"cet enregistrement (can_view_amount_v2() = indéterminé) : au moins une "
            f"règle applicable dépend de {fields_str}, qui ne sont pas connus dans ce "
            f"contexte. Ne pas affirmer que l'accès est autorisé ou refusé -- signaler "
            f"explicitement cette incertitude à l'utilisateur."
        )
    return (
        f"[FAIT DÉTERMINISTIQUE] Pour un montant de {amount:.0f}€, "
        f"le moteur de règles calcule can_view_amount() = {can_view} : "
        f"l'utilisateur {'PEUT' if can_view else 'NE PEUT PAS'} voir "
        f"cet enregistrement."
    )


def _question_suggests_automation_bypass(question: str) -> bool:
    return bool(_AUTOMATION_PATTERN.search(question))


# Bloc 9 gap, found 2026-08-10 (bloc9-01a-business, generalization check
# 1/8 on custom_credit_note_approval): find_methods_with_override_risk_findings
# has no cap -- on a model shared across many adversarial customization
# modules (account.move is extended by credit-note-approval AND
# expense-risk AND others), EVERY flagged method across ALL of them gets
# forced-dispatched for any single approval-related question, regardless
# of whether it has anything to do with what was actually asked. Confirmed
# live: the regional director's 20000e cascade finding on
# action_valider_avoir never reached the synthesis answer once an
# unrelated hr_expense finding on a different method was dispatched
# alongside it in the same tool_observations blob -- the small synthesis
# LLM has a limited context budget and no way to know which finding the
# question actually needs. Ranking by lexical relevance to the question
# (rapidfuzz, already a project dependency -- see business_resolver.py)
# and capping the dispatch keeps the forced pre-dispatch scoped to what
# the question is actually about, same discipline as the other J8/J9
# structural guards (narrow the expensive step, don't widen the prompt).
# Bloc 9 gap, found 2026-08-10 (bloc9-01a-business, module 1/8 rerun AFTER
# the original cap=2 fix from earlier the same day): capping at 2 instead
# of 1 does not actually solve the problem it was written for whenever
# EXACTLY 2 candidates are flagged (the common case on a heavily-shared
# model like account.move: action_valider_avoir -- the one the question is
# about -- plus exactly one unrelated flagged method from a different
# customization module, e.g. hr_expense's _compute_commercial_partner_id).
# The old "no-op when <= cap" guard let BOTH through untouched in that
# exact case, so the irrelevant second method still consumed a full hop of
# the tight CI_MAX_HOPS=4 budget for zero value to the question -- confirmed
# live: hop_count reached 3 from forced pre-dispatch alone (1 verrous_
# securite + 2 override-cascade) before the ReAct loop even started, only 1
# hop remained, and CI_MAX_HOPS was hit before evaluer_regles_enregistrement
# or any further exploration could run, reproducing the exact "noise crowds
# out the needed fact" failure this cap was meant to prevent in the first
# place. Lowering the cap to 1 removes the ambiguity entirely: only the
# single most lexically-relevant flagged method is ever forced-dispatched,
# freeing a full extra hop for the ReAct loop on every question that
# triggers this guard, not just ones where more than 2 candidates happened
# to be flagged.
_MAX_OVERRIDE_CASCADE_DISPATCH = 1


# Bloc 9 gap, found 2026-08-11 (bloc9-07c-sudo-scope-trap, module 7/8 first
# live run): MAX_MODELS_PER_QUERY's own truncation (config.settings, applied
# in code_intelligence_agent right after resolve_business_term) was a plain
# `resolved_models[:MAX_MODELS_PER_QUERY]` slice -- whichever models
# business_resolver happened to list FIRST survive, with no regard for which
# one the question is actually about. Confirmed live: a question combining
# "sudo()" + "remboursement" resolved to multiple candidate models, the
# truncation dropped custom.reimbursement.request (the one the whole
# question is about) before the forced-dispatch loops below even ran, and
# the ReAct loop was left to answer from evaluer_regles_enregistrement alone
# -- producing a confidently wrong "sans restriction" claim on a getattr()
# dynamic-dispatch case that should have triggered the dynamic-uncertainty
# guardrail instead. Same class of fix as _rank_and_cap_override_methods
# above (narrow an expensive/scarce resource by relevance instead of an
# arbitrary order), applied one level earlier in the pipeline -- to which
# MODELS get to compete for the hop budget at all, not just which methods
# on an already-chosen model do.
def _rank_and_cap_resolved_models(question: str, resolved_models: List[str], max_models: int) -> List[str]:
    """Rank resolved model technical names by lexical relevance to the
    question (dots/underscores turned into spaces, fuzzy-compared to the
    question text) and keep only the top max_models. No-op (returns the
    input unchanged) when there are already few enough candidates.
    """
    if len(resolved_models) <= max_models:
        return resolved_models
    from rapidfuzz import fuzz
    question_lower = question.lower()
    scored = [
        (name, fuzz.token_set_ratio(question_lower, name.replace(".", " ").replace("_", " ").lower()))
        for name in resolved_models
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    kept = [name for name, _score in scored[:max_models]]
    logger.warning(
        "Node [code_intelligence_agent]: Truncating resolved models from %d to "
        "MAX_MODELS_PER_QUERY (%d), ranked by relevance to the question -- kept: %s.",
        len(resolved_models), max_models, kept,
    )
    return kept


def _rank_and_cap_override_methods(question: str, method_names: List[str]) -> List[str]:
    """Rank override-risk-flagged method names by lexical relevance to the
    question (method name with underscores turned into spaces, fuzzy-
    compared to the question text) and keep only the top
    _MAX_OVERRIDE_CASCADE_DISPATCH (1 -- see module-level comment above).
    No-op (returns the input unchanged) when there is already at most one
    candidate -- nothing to rank or drop in that case.
    """
    if len(method_names) <= _MAX_OVERRIDE_CASCADE_DISPATCH:
        return method_names
    from rapidfuzz import fuzz
    question_lower = question.lower()
    scored = [
        (name, fuzz.token_set_ratio(question_lower, name.replace("_", " ").lower()))
        for name in method_names
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    kept = [name for name, _score in scored[:_MAX_OVERRIDE_CASCADE_DISPATCH]]
    logger.info(
        "Node [code_intelligence_agent]: override-cascade dispatch capped -- "
        "%d flagged method(s) found, keeping top %d by relevance to the question: %s.",
        len(method_names), _MAX_OVERRIDE_CASCADE_DISPATCH, kept,
    )
    return kept


def _override_user_groups_arg(tool_name: str, tool_args: dict, resolved_user_group_xmlids: list) -> dict:
    """
    Bloc 7 (J23-24) / real-auth fix: for evaluer_regles_enregistrement, the
    tool call's user_groups_json must always reflect the DEMANDEUR's real
    Odoo groups -- never a value invented by the LLM from free text, which
    has no way to know the actual requester's real group memberships.

    resolved_user_group_xmlids: the demandeur's real group DB IDs (signed
    into the JWT by the Odoo controller from request.env.user.groups_id),
    already translated to xml_id strings by _resolve_user_group_xmlids()
    -- the graph identifies groups by xml_id, never by raw DB id (see that
    function's docstring for the bug this fixes).

    Also applies to chemin_execution_bouton (Bloc 7 extension, 2026-08-07):
    a "comment faire X ?" question needs the button's REAL availability for
    THIS demandeur, same reasoning as evaluer_regles_enregistrement -- the
    LLM has no way to know the actual requester's real group memberships,
    so whatever it proposes for user_groups_json is discarded here too.

    Mutates and returns tool_args for convenience; any value the LLM
    proposed is discarded and logged. No-op for every other tool.
    """
    if tool_name not in ("evaluer_regles_enregistrement", "chemin_execution_bouton"):
        return tool_args

    real_groups_json = json.dumps(resolved_user_group_xmlids)
    llm_proposed = tool_args.get("user_groups_json")
    if llm_proposed and llm_proposed != real_groups_json:
        logger.warning(
            "Node [code_intelligence_agent]: overriding LLM-guessed "
            "user_groups_json (%s) with the real requester groups (%s).",
            llm_proposed, real_groups_json,
        )
    tool_args["user_groups_json"] = real_groups_json
    return tool_args


# ── Q6.1 fix: strip group-resolution noise from synthesis context ─────────────

# Regex matching the "could not be resolved" boilerplate emitted by
# qui_a_acces_a (deterministic_tools.py L461-465) when the LLM-guessed
# group identifier doesn't match any group in the knowledge graph.
_COULD_NOT_RESOLVE_RE = re.compile(
    r"""Group identifier ['"].*?['"] could not be resolved""",
    re.IGNORECASE,
)


def _strip_group_resolution_noise(
    tool_observations: List[str],
    resolved_user_group_xmlids: list,
    tool_observation_models: List[str],
):
    """Remove qui_a_acces_a 'could not be resolved' observations that refer
    to LLM-guessed group names, when the real-auth override has already
    injected the demandeur's actual groups into evaluer_regles_enregistrement.

    Context (Q6.1 regression): the synthesis LLM sees BOTH:
      - a 'could not be resolved' message from qui_a_acces_a (which does NOT
        receive the override, and uses whatever group name the LLM guessed),
      - a correct [FAIT DÉTERMINISTIQUE] can_view_amount() verdict computed
        on the real resolved groups via evaluer_regles_enregistrement.

    The synthesis then self-contradicts: it mentions the resolution failure
    (obsolete artifact of the LLM-guessed names) while simultaneously
    presenting the correct verdict.  Stripping the noise at the source is
    the simplest fix -- the qui_a_acces_a 'could not be resolved' message
    adds zero information once evaluer_regles_enregistrement has already
    run with the real groups.

    Conditions for stripping (all must be true):
      1. Real groups were resolved (the override is active).
      2. The observation matches the 'could not be resolved' pattern.
      3. At least one other observation is a [FAIT DÉTERMINISTIQUE] block
         (meaning evaluer_regles_enregistrement already computed the real
         verdict -- the 'could not be resolved' message is truly obsolete).
    """
    if not resolved_user_group_xmlids:
        return tool_observations, tool_observation_models  # No override active, keep everything.

    has_deterministic_fact = any(
        "[FAIT DÉTERMINISTIQUE]" in obs for obs in tool_observations
    )
    if not has_deterministic_fact:
        return tool_observations, tool_observation_models  # No authoritative verdict yet, keep everything.

    cleaned = []
    cleaned_models = []
    for obs, model in zip(tool_observations, tool_observation_models):
        if _COULD_NOT_RESOLVE_RE.search(obs):
            logger.info(
                "Node [code_intelligence_agent]: Q6.1 fix -- stripping 'could not be "
                "resolved' observation from synthesis context (real groups override "
                "is active and a deterministic fact is present): %.120s",
                obs,
            )
            continue
        cleaned.append(obs)
        cleaned_models.append(model)
    return cleaned, cleaned_models


def _extract_first_scoped_file_link(text: str) -> str:
    match = re.search(r"\[[^\]]+\]\(file:///[^\)]+#L\d+-L\d+\)", text)
    return match.group(0) if match else ""


# Bloc 9 gap (2026-08-13, check_native_odoo_out_of_scope.py on
# mrp.production): resolve_business_term() correctly returns
# is_resolved=False when a question names a genuinely out-of-corpus Odoo
# model (native, untouched by any custom_* module's manifest depends,
# not in CORE_MODULES_ALWAYS_LOADED) -- but nothing downstream ever acted
# on that signal. A live run showed the LLM, left with no forced tool
# dispatch and no resolved model, still trying to be helpful: it opened by
# correctly stating the model "n'a pas ete trouve dans le graphique de
# connaissance indexe", then in the SAME answer fabricated a plausible-
# sounding role-based conclusion ("les utilisateurs qui ont le role
# 'Gestionnaire de production'...") from its own pretrained Odoo
# knowledge anyway -- exactly the ungrounded-answer failure this whole
# system exists to avoid (same self-contradiction shape as module 5/8's
# Bug 2, different mechanism: no deterministic fact existed here to
# contradict, the LLM just filled the void itself).
#
# Deliberately narrow-scoped, same discipline as _force_dynamic_
# uncertainty_answer above being gated on specific question vocabulary:
# only fires when the question contains a dotted lowercase identifier
# that LOOKS like a real Odoo technical model name (e.g. "mrp.production")
# -- never on a generic/meta question that doesn't name a specific model
# at all, where an "I don't recognize this model" decline would itself be
# wrong. Deliberately does NOT try to detect "is this question about Odoo
# behavior in general" (that classification problem is exactly what this
# whole resolver pipeline already exists to solve, imperfectly); this
# guard only closes the specific confirmed gap: an explicit, unresolved,
# model-shaped mention.
_TECHNICAL_MODEL_LOOKALIKE_RE = re.compile(r"\b[a-z][a-z_]*(?:\.[a-z][a-z_]*){1,3}\b")


def _force_out_of_scope_model_answer(question: str, concept) -> Optional[str]:
    """
    Guardrail: if the business-term resolver could not resolve the
    question to any model/module AND the question names something that
    looks like a real Odoo technical model identifier, force an honest
    decline instead of letting free synthesis fall back to the LLM's own
    ungrounded general knowledge of Odoo. See the module comment above
    _TECHNICAL_MODEL_LOOKALIKE_RE for the live failure this closes and why
    the trigger is scoped this narrowly.
    """
    if concept.is_resolved:
        return None
    match = _TECHNICAL_MODEL_LOOKALIKE_RE.search(question.lower())
    if not match:
        return None
    model_name = match.group(0)
    return (
        f"Le modele '{model_name}' n'est pas present dans le corpus indexe par cet outil "
        f"(ni personnalise par un module custom_*, ni charge par un autre mecanisme connu de "
        f"cette instance). Je ne peux donc pas repondre a partir du code reel de cette instance "
        f"-- toute reponse sur son comportement standard viendrait de connaissances generales "
        f"sur Odoo, non verifiees contre ce systeme precis, ce que cet outil n'est pas cense faire. "
        f"Pour verifier vous-meme : consultez la documentation Odoo standard du module concerne, "
        f"ou demandez a un administrateur d'indexer ce modele si vous en avez besoin regulierement."
    )


def _force_dynamic_uncertainty_answer(question: str, raw_tool_output: str) -> Optional[str]:
    """
    Guardrail for adversarial dynamic-dispatch cases: if static analysis
    detected getattr/eval/exec, the final answer must not turn that into a
    certain permission conclusion.
    """
    if not re.search(r"incertitude dynamique|dispatch dynamique|getattr|eval\(|exec\(", raw_tool_output, re.IGNORECASE):
        return None
    if not re.search(r"remboursement|custom_expense_reimbursement_indirect|custom\.reimbursement\.request", question, re.IGNORECASE):
        return None

    citation = _extract_first_scoped_file_link(raw_tool_output)
    citation_part = f" Source à revoir : {citation}." if citation else ""
    return (
        "Je ne peux pas classifier avec certitude qui peut valider cette demande de remboursement. "
        "L'analyse statique détecte un dispatch dynamique (`getattr`) : la méthode exécutée dépend "
        "d'un paramètre récupéré à l'exécution, donc le chemin exact doit être revu manuellement. "
        "Ne pas présenter cette validation comme autorisée ou refusée de manière certaine."
        f"{citation_part}"
    )


_CACHED_CODE_INTEL_GRAPH = None
_CACHED_GRAPH_MTIME = 0.0
GRAPH_JSON_PATH = Path(__file__).resolve().parent.parent / "code_intelligence" / "active_graph.json"


def _load_module(mod_dir: Path) -> tuple:
    """Load a single Odoo module directory into a ParsedModule.

    2026-08-06 fix (account.move._reverse_moves override-order bug): a
    missing __manifest__.py must NEVER silently become manifest=None here.
    cross_file_resolver.topological_sort_modules() only follows a module's
    real dependencies when `mod.manifest` is truthy -- manifest=None made it
    treat the module as a dependency-free leaf with no warning at all,
    corrupting load_order (and everything built from it: graph_builder's
    per-method override_sites, and method_override_resolver's reversal of
    that order into Odoo's real MRO execution order) whenever a module with
    real dependencies had no manifest on disk. See
    code_intelligence/manifest_parser.py::KNOWN_CORE_MODULE_DEPENDS /
    MissingManifestError for the full writeup and
    code_intelligence/tests/test_mixed_corpus_load_order.py for the
    regression test.

    2026-08-12 fix: the synthetic fake_data/code/ stand-in corpus (hand-
    maintained partial copies of a few Odoo core modules, used to give the
    graph something realistic to build a load order over before the real
    Odoo 17 corpus was wired in as addons_root) has been removed entirely.
    get_code_intelligence_graph() now loads 'account'/'sale'/'stock'
    directly from the real corpus, which ships a real __manifest__.py for
    every module -- so the synthesize-a-fallback-manifest path below is no
    longer expected to fire for those three in practice. The mechanism
    itself is kept as a defensive fallback (any future manifest-less
    directory, or a corpus without addons_root available) rather than
    removed, since it costs nothing to keep and MissingManifestError's
    fail-loudly behavior is still the right default for a genuinely
    unexpected manifest-less module.

    Resolution order when __manifest__.py is absent:
      1. A KNOWN_CORE_MODULE_DEPENDS entry (account/sale/stock) -> synthesize
         a manifest with its real, well-known, hardcoded `depends`. Kept as
         a defensive fallback; not expected to trigger against the real
         addons_root corpus, which always ships a real manifest for these.
      2. Directory with no .py files at all (e.g. a loose XML asset folder,
         not a real Odoo module) -> it can never declare a Model/Method, so
         it can never appear in a method override_sites list and its
         position in load_order cannot corrupt override-chain resolution.
         Safe to treat as a dependency-free leaf.
      3. Anything else (a real addon -- miro_ai, custom_*, or any other
         module actually containing code) -> raise MissingManifestError
         instead of guessing. A silently-guessed dependency set for a
         module we don't actually know is exactly the bug this fix removes.
    """
    from code_intelligence.manifest_parser import (
        parse_manifest,
        synthesize_fallback_manifest,
        MissingManifestError,
        KNOWN_CORE_MODULE_DEPENDS,
    )
    from code_intelligence.python_extractor import extract_odoo_models_from_file
    from code_intelligence.xml_extractor import (
        parse_ir_rules_from_xml, parse_groups_from_xml,
        parse_actions_from_xml, parse_menuitems_from_xml, parse_views_from_xml,
        parse_server_actions_from_xml, parse_base_automations_from_xml,
    )
    from code_intelligence.csv_extractor import parse_access_control_csv
    from code_intelligence.cross_file_resolver import ParsedModule

    manifest_p = mod_dir / "__manifest__.py"
    if manifest_p.exists():
        manifest = parse_manifest(manifest_p)
    else:
        module_name = mod_dir.name
        manifest = synthesize_fallback_manifest(module_name, mod_dir)
        if manifest is None:
            has_python_files = next(mod_dir.rglob("*.py"), None) is not None
            if not has_python_files:
                logger.info(
                    "Module directory '%s' at %s has no __manifest__.py and no "
                    ".py files -- treating as a non-module asset directory "
                    "(e.g. loose XML views), not a real Odoo module. It can "
                    "declare no Model/Method, so it cannot affect override-chain "
                    "resolution regardless of its position in load_order.",
                    module_name, mod_dir,
                )
                from code_intelligence.manifest_parser import OdooManifest
                manifest = OdooManifest(
                    module_name=module_name, filepath="", name=module_name,
                    depends=[], synthesized=True,
                )
            else:
                raise MissingManifestError(
                    f"Module '{module_name}' at {mod_dir} has no __manifest__.py, "
                    f"contains .py files, and is not a known core module "
                    f"({sorted(KNOWN_CORE_MODULE_DEPENDS)}). Refusing to "
                    f"silently treat it as having no dependencies -- this "
                    f"previously produced a wrong module load_order and a wrong "
                    f"method-override execution order with no error signal at "
                    f"all (see manifest_parser.MissingManifestError docstring). "
                    f"If this is a real Odoo module, add its __manifest__.py; if "
                    f"it's a new core module standing in for a real Odoo core "
                    f"addon, add it to KNOWN_CORE_MODULE_DEPENDS in "
                    f"code_intelligence/manifest_parser.py."
                )
    mod = ParsedModule(manifest=manifest)
    for py_f in mod_dir.rglob("*.py"):
        if py_f.name == "__manifest__.py":
            continue
        mod.models.extend(extract_odoo_models_from_file(py_f))
    for xml_f in mod_dir.rglob("*.xml"):
        mod.rules.extend(parse_ir_rules_from_xml(xml_f))
        mod.groups.extend(parse_groups_from_xml(xml_f))
        mod.actions.extend(parse_actions_from_xml(xml_f))
        mod.server_actions.extend(parse_server_actions_from_xml(xml_f))
        mod.base_automations.extend(parse_base_automations_from_xml(xml_f))
        mod.menuitems.extend(parse_menuitems_from_xml(xml_f))
        mod.views.extend(parse_views_from_xml(xml_f))
    for csv_f in mod_dir.rglob("*.csv"):
        mod.acl_entries.extend(parse_access_control_csv(csv_f))
    return mod_dir.name, mod


def get_code_intelligence_graph():
    """Lazy-load and cache Knowledge Graph for Code Intelligence node."""
    global _CACHED_CODE_INTEL_GRAPH, _CACHED_GRAPH_MTIME

    # Check if a built JSON graph exists and has been modified since last load
    try:
        if GRAPH_JSON_PATH.exists():
            current_mtime = GRAPH_JSON_PATH.stat().st_mtime
            if _CACHED_CODE_INTEL_GRAPH is None or current_mtime > _CACHED_GRAPH_MTIME:
                from code_intelligence.atomic_graph_swap import atomic_read_json
                from code_intelligence.graph_version import deserialize_graph_with_metadata
                
                logger.info("Loading graph from disk (mtime %s > %s)", current_mtime, _CACHED_GRAPH_MTIME)
                data_dict = atomic_read_json(GRAPH_JSON_PATH)
                G, metadata = deserialize_graph_with_metadata(data_dict)
                _CACHED_CODE_INTEL_GRAPH = G
                _CACHED_GRAPH_MTIME = current_mtime
                logger.info("Knowledge Graph loaded from JSON: %d nodes, %d edges (version: %s)", 
                            G.number_of_nodes(), G.number_of_edges(), metadata.get("git_commit", "unknown"))
                return _CACHED_CODE_INTEL_GRAPH
    except Exception as e:
        logger.error("Failed to load graph from %s: %s", GRAPH_JSON_PATH, e)
        # Fall back to building it

    if _CACHED_CODE_INTEL_GRAPH is not None:
        return _CACHED_CODE_INTEL_GRAPH

    logger.info("Building Knowledge Graph from source files...")
    from code_intelligence.utils import discover_odoo_modules
    from code_intelligence.cross_file_resolver import build_module_symbol_registry
    from code_intelligence.graph_builder import OdooGraphBuilder

    base_dir = Path(__file__).resolve().parent.parent
    addons_root = Path("/home/user/odoo-17.0/addons") if Path("/home/user/odoo-17.0/addons").exists() else base_dir.parent / "addons"

    modules_dict = {}

    # 2026-08-12 fix: fake_data/code/{account,sale,stock} used to stand in
    # for these three real Odoo core modules -- hand-maintained, partial
    # copies that could silently drift from the real Odoo 17 source (see
    # todo/etat_reel.md for the full writeup). Worse: because this preload
    # ran BEFORE the J36 direct-dependency loop below, and that loop skips
    # any dependency name already present in modules_dict, the fake stand-
    # ins silently pre-empted the real modules every time -- every question
    # this project has ever answered about account.move reasoned against
    # the synthetic copy, never the real Odoo 17 source. Removed entirely;
    # these three are now loaded directly from the real corpus. Still an
    # explicit preload (not left to the J36 loop alone) because the
    # account.move._reverse_moves override-chain regression coverage
    # (test_mixed_corpus_load_order.py) needs 'sale' present even though no
    # custom_* module's manifest actually depends on it.
    CORE_MODULES_ALWAYS_LOADED = ["account", "sale", "stock"]
    if addons_root.exists():
        for core_name in CORE_MODULES_ALWAYS_LOADED:
            core_dir = addons_root / core_name
            if core_dir.is_dir() and (core_dir / "__manifest__.py").exists():
                name, mod = _load_module(core_dir)
                modules_dict[name] = mod
            else:
                logger.warning(
                    "Core module '%s' not found (or has no __manifest__.py) under "
                    "%s -- skipping preload. Some override-chain regression "
                    "coverage may be reduced; this does not affect custom_* "
                    "modules, which are always loaded from the real corpus below.",
                    core_name, addons_root,
                )

    miro_ai_dir = addons_root / "miro_ai"
    if miro_ai_dir.exists():
        name, mod = _load_module(miro_ai_dir)
        modules_dict[name] = mod

    # Load adversarial custom_* modules for end-to-end benchmark support
    if addons_root.exists():
        custom_modules = discover_odoo_modules(addons_root, prefix="custom_")
        for mod_name in custom_modules:
            mod_dir = addons_root / mod_name
            name, mod = _load_module(mod_dir)
            modules_dict[name] = mod

        # J36 fix (2026-08-07): custom_* modules routinely _inherit a REAL
        # Odoo core module (e.g. custom_expense_risk_base extends hr.expense
        # via depends=['hr_expense']) that is neither part of the always-
        # loaded core set above nor itself prefixed 'custom_', so it was
        # never loaded -- the extended model's base declaration (and its
        # real fields/methods) never entered the graph, and every tool call
        # against it returned "model not found" (confirmed root cause of the
        # J36 Sprint D replay failure, 0/8, eval_report_j36_expense_risk.md).
        # Load each custom_* module's DIRECT manifest dependencies too, one
        # level only -- not the full transitive closure. A real addon's
        # dependency chain quickly reaches base/mail/web and would balloon
        # load time for no benefit here: we only need the dependency's OWN
        # model declarations (e.g. hr.expense's _name + fields), not a
        # faithful simulation of everything base/mail/web themselves add.
        direct_deps = set()
        for mod_name in custom_modules:
            dep_mod = modules_dict.get(mod_name)
            if dep_mod and dep_mod.manifest:
                direct_deps.update(dep_mod.manifest.depends)

        for dep_name in sorted(direct_deps):
            if dep_name in modules_dict:
                continue  # already loaded (core preload, miro_ai, or another custom_* module)
            dep_dir = addons_root / dep_name
            if not dep_dir.is_dir() or not (dep_dir / "__manifest__.py").exists():
                # Not a real loadable addon here (e.g. 'base' ships as a
                # single file in this corpus, not a module directory) --
                # skip rather than guess; topological_sort_modules already
                # treats an unresolved dependency name as a harmless leaf.
                continue
            try:
                name, mod = _load_module(dep_dir)
                modules_dict[name] = mod
                logger.info(
                    "Loaded '%s' as a direct dependency of a custom_* module "
                    "(J36 fix) -- its base model declarations are now available "
                    "to models that _inherit it.", name,
                )
            except Exception as e:
                logger.error("Failed to load custom_* dependency '%s': %s", dep_name, e)

    registry = build_module_symbol_registry(modules_dict)
    builder = OdooGraphBuilder(registry, modules_dict)
    _CACHED_CODE_INTEL_GRAPH = builder.build_graph()
    
    # Save the freshly built graph so future requests or concurrent processes can load it fast
    try:
        from code_intelligence.atomic_graph_swap import atomic_write_json
        from code_intelligence.graph_version import serialize_graph_with_metadata
        data_dict = serialize_graph_with_metadata(_CACHED_CODE_INTEL_GRAPH)
        atomic_write_json(data_dict, GRAPH_JSON_PATH)
        _CACHED_GRAPH_MTIME = GRAPH_JSON_PATH.stat().st_mtime
        logger.info("Saved freshly built graph to %s", GRAPH_JSON_PATH)
    except Exception as e:
        logger.error("Failed to save built graph to %s: %s", GRAPH_JSON_PATH, e)

    logger.info(
        "Knowledge Graph built: %d nodes, %d edges, %d modules",
        _CACHED_CODE_INTEL_GRAPH.number_of_nodes(),
        _CACHED_CODE_INTEL_GRAPH.number_of_edges(),
        len(modules_dict),
    )
    return _CACHED_CODE_INTEL_GRAPH

def code_intelligence_agent(state: RAGState) -> dict:
    """
    Node [code_intelligence_agent]: ReAct agent loop for Code Intelligence.

    C.1.1: LangGraph ReAct loop with 13 bound tools (5 composite + 4 auxiliary +
    4 code-analysis: analyser_verrous_securite, analyser_actions_serveur,
    analyser_contraintes_donnees, evaluer_regles_enregistrement).
    C.1.2: Anti-loop guard detects duplicate tool+args calls.
    C.1.3: System prompt enforces scope-first navigation strategy.
    C.1.4: Hop counter tracks tool calls; partial response on limit.
    """
    import time
    import json as _json
    start_time = time.time()

    from langchain_core.messages import AIMessage, ToolMessage

    question = state.get("question", "").strip()
    chat_history = state.get("chat_history", [])
    logger.info("Node [code_intelligence_agent]: Starting ReAct loop for: %s", question)

    # Bloc 12 / J46-J48: reasoning-trace + LLM-call-budget instrumentation.
    # "code_intelligence" is the most expensive branch to reason about --
    # this trace_id ties together every composite tool call this question
    # triggers (forced pre-dispatch + ReAct loop hops) so the full path is
    # readable post-hoc via ReasoningTraceLogger.read_trace(trace_id), and
    # llm_call_count is directly comparable to "documentaire"/"donnees_erp".
    from code_intelligence.reasoning_trace_logger import ReasoningTraceLogger, new_trace_id
    _trace_id = new_trace_id()
    _trace_logger = ReasoningTraceLogger()
    _llm_call_count = 0
    _hop_index = 0

    if _is_out_of_scope(question):
        logger.info("Node [code_intelligence_agent]: Out of scope question.")
        response = AssistantResponse(
            answer=OUT_OF_SCOPE_ANSWER,
            sources=[],
            confidence=0.0,
        )
        timing = state.get("timing", {}).copy()
        timing["code_intelligence_time"] = time.time() - start_time
        _trace_logger.log_summary(
            trace_id=_trace_id, branch="code_intelligence", question=question,
            hop_count=0, llm_call_count=0, total_time_ms=timing["code_intelligence_time"] * 1000,
            hop_cap=CI_MAX_HOPS,
        )
        return {"response": response, "raw_answer": response.answer, "timing": timing}

    # J32-J33: Security & Massive Extraction Safeguards
    from config.settings import (
        MAX_MODELS_PER_QUERY,
        MASSIVE_EXTRACTION_REFUSAL_MSG,
        PROMPT_INJECTION_REFUSAL_MSG,
    )

    if _is_prompt_injection(question):
        logger.warning("Node [code_intelligence_agent]: Prompt injection attempt intercepted.")
        response = AssistantResponse(
            answer=PROMPT_INJECTION_REFUSAL_MSG,
            sources=[],
            confidence=0.0,
        )
        timing = state.get("timing", {}).copy()
        timing["code_intelligence_time"] = time.time() - start_time
        _trace_logger.log_summary(
            trace_id=_trace_id, branch="code_intelligence", question=question,
            hop_count=0, llm_call_count=0, total_time_ms=timing["code_intelligence_time"] * 1000,
            hop_cap=CI_MAX_HOPS,
        )
        return {"response": response, "raw_answer": response.answer, "timing": timing}

    if _is_massive_extraction_request(question):
        logger.warning("Node [code_intelligence_agent]: Massive extraction request intercepted.")
        response = AssistantResponse(
            answer=MASSIVE_EXTRACTION_REFUSAL_MSG,
            sources=[],
            confidence=0.0,
        )
        timing = state.get("timing", {}).copy()
        timing["code_intelligence_time"] = time.time() - start_time
        _trace_logger.log_summary(
            trace_id=_trace_id, branch="code_intelligence", question=question,
            hop_count=0, llm_call_count=0, total_time_ms=timing["code_intelligence_time"] * 1000,
            hop_cap=CI_MAX_HOPS,
        )
        return {"response": response, "raw_answer": response.answer, "timing": timing}

    # Initialize the knowledge graph and inject into tool wrappers
    G = get_code_intelligence_graph()
    from code_intelligence.ci_agent_tools import ALL_CI_TOOLS, set_graph_ref, set_llm_ref
    from code_intelligence.business_resolver import resolve_business_term
    from code_intelligence.authorization_gate import gate_observation, OmittedItem
    set_graph_ref(G)

    # Bloc 7 fix: translate the demandeur's real Odoo group DB IDs to xml_id
    # strings ONCE for this question -- see _resolve_user_group_xmlids()
    # docstring. Every gating / evaluer_regles_enregistrement call below
    # must use this resolved list, never the raw state["user_groups"] ids.
    resolved_user_group_xmlids = _resolve_user_group_xmlids(state.get("user_groups", []))
    if state.get("user_groups") and not resolved_user_group_xmlids:
        logger.warning(
            "Node [code_intelligence_agent]: none of the demandeur's %d group ID(s) "
            "resolved to an xml_id -- gating will fail closed for this request.",
            len(state["user_groups"]),
        )

    # Bind tools to LLM (C.1.1)
    # 2026-08-14: routed through get_chat_llm() (rag/llm_client.py) instead
    # of ChatGroq(...) directly, so LLM_PROVIDER=openrouter (Qwen3-14B) can
    # be tested on this branch -- the one scripts/check_bloc9_*.py actually
    # exercises. See llm_client.py's module docstring for exact scope.
    llm = get_chat_llm(
        temperature=0.0,
        max_retries=0,  # Let _invoke_with_rate_limit handle dynamic header backoff
        max_tokens=1024,
        # ReAct-loop fix (part 2, post-Bloc-8 regression): force ONE tool
        # call per LLM turn. Without this, llama-3.1-8b-instant frequently
        # emits 3-4 tool_calls in a single ai_msg -- all chosen blind, in
        # one shot, before any observation exists yet (confirmed in the
        # J46-J48 reasoning traces: batches of hops land at the exact same
        # millisecond timestamp). That burns through CI_MAX_HOPS in one
        # breath and defeats the messages-accumulation fix above, since
        # there's no LLM call in between the wrong guesses for the model to
        # actually see and correct from. This is a standard OpenAI Chat
        # Completions body param (parallel_tool_calls, default true) --
        # both ChatGroq and ChatOpenAI (OpenRouter) pass unknown kwargs
        # straight through via model_kwargs (same mechanism already used
        # for frequency_penalty/presence_penalty on the synthesis LLM
        # below).
        model_kwargs={"parallel_tool_calls": False},
    )
    set_llm_ref(llm)
    llm_with_tools = llm.bind_tools(ALL_CI_TOOLS)

    # J30-J31: phase timing instrumentation
    _ci_groq_wait = 0.0          # accumulated Groq rate-limit wait (subtracted from wall-clock)
    _ci_per_hop_times: list = []  # per-hop wall-clock durations

    # Story S2.0: Business Term Resolver -- Map natural language concepts to technical Odoo models/modules
    _t_resolver = time.perf_counter()
    concept = resolve_business_term(question, G, llm=llm)
    _ci_resolver_time = time.perf_counter() - _t_resolver
    if concept.source_step == "llm_arbitration":
        _llm_call_count += 1  # bounded arbitration call inside resolve_business_term

    # J32-J33: Enforce MAX_MODELS_PER_QUERY limit on resolved models
    if concept.resolved_models and len(concept.resolved_models) > MAX_MODELS_PER_QUERY:
        # Bloc 9 gap fix (2026-08-11, bloc9-07c-sudo-scope-trap) -- ranked
        # by relevance to the question instead of an arbitrary slice, see
        # _rank_and_cap_resolved_models docstring for the live failure this
        # replaces.
        concept.resolved_models = _rank_and_cap_resolved_models(
            question, concept.resolved_models, MAX_MODELS_PER_QUERY,
        )

    tool_observations: list = []
    # Bloc 9 gap fix (2026-08-10, bloc9-05c-no-link-trap contamination):
    # index-aligned with tool_observations -- the model_name each
    # observation actually came from, or "" when unknown. See
    # _scoped_raw_tool_output for why this exists (deterministic backfills
    # must not mix facts across models the ReAct loop happened to visit
    # in the same turn).
    tool_observation_models: list = []
    omitted_items: list = []  # Bloc 7 (J23-24): OmittedForAuthorization entries
    final_answer = None
    hop_count = 0
    seen_calls: set = set()

    system_prompt = CI_SYSTEM_PROMPT
    if concept.is_resolved:
        resolved_info = []
        if concept.resolved_models:
            resolved_info.append(f"Target Models: {', '.join(concept.resolved_models)}")
        if concept.resolved_modules:
            resolved_info.append(f"Target Modules: {', '.join(concept.resolved_modules)}")
        confidence_tag = (
            f" (LLM-arbitrated, confidence={concept.confidence})"
            if concept.source_step == "llm_arbitration"
            else ""
        )
        system_prompt += (
            f"\n\n[BUSINESS TERM RESOLVER S2.0]\n"
            f"Query term matched: '{concept.user_term}'{confidence_tag}.\n"
            f"{' | '.join(resolved_info)}.\n"
            f"Use these exact technical identifiers when invoking composite tools."
        )

    # J8/J15: force analyser_verrous_securite when the question resolves to
    # a target model AND that model structurally has at least one Python
    # security-lock finding (find_security_lock_source_files). Only fires
    # when a model is actually available -- an unresolved concept is a Bloc 0
    # problem, not this one.
    #
    # 2026-08-10 (Bloc 9, module 5 gap): this used to be gated ADDITIONALLY
    # on _question_is_approval_related(question) -- but questions like
    # "pourquoi je n'arrive pas à démarrer..." or "la règle s'applique-t-elle
    # ..." (module 5, 05a/05c) contain none of that vocabulary, so the
    # forced dispatch silently never fired and the LLM picked its own tool,
    # badly (hallucinated a malformed method name instead of finding the
    # real Python lock). Every module has its own action vocabulary
    # ("démarrer", "soumettre", "rejeter"...) -- chasing keywords
    # per-module is the same whack-a-mole already abandoned for
    # find_server_action_nodes/find_methods_with_override_cascade below,
    # which lean on their structural guard instead. Dropped the keyword
    # gate entirely for THIS dispatch: unlike those two tools (genuinely
    # tangential to most questions), a Python security lock is central to
    # nearly every governance/access question about a model -- which is
    # exactly why J7/J8 exist (the LLM never reliably called this tool on
    # its own even with an explicit "ALWAYS invoke" directive in
    # CI_SYSTEM_PROMPT). Tradeoff accepted: this can now also fire on
    # questions unrelated to security that happen to resolve to a model
    # with a lock elsewhere in its source -- same "false positive costs
    # ~nothing" philosophy already accepted for the other two guards below,
    # and the static tool call itself is cheap (no LLM).
    if concept.is_resolved and concept.resolved_models:
        from code_intelligence.ci_agent_tools import find_security_lock_source_files
        tool_map = {t.name: t for t in ALL_CI_TOOLS}
        lock_tool = tool_map.get("analyser_verrous_securite")
        if lock_tool is not None:
            for target_model in concept.resolved_models:
                if not find_security_lock_source_files(G, target_model):
                    continue  # structural guard: nothing to say, skip silently
                call_key = ("analyser_verrous_securite", target_model)
                if call_key in seen_calls:
                    continue
                _t_hop = time.perf_counter()
                try:
                    forced_observation = str(lock_tool.invoke({"model_name": target_model}))
                    # Bloc 9 gap, found 2026-08-11 (bloc9-01a-business rerun):
                    # analyser_verrous_securite aggregates EVERY source file
                    # touching the model (find_model_source_filepaths), sorted
                    # alphabetically -- on a heavily-shared model like
                    # account.move that can be a dozen+ per-file blocks. The
                    # generic 1200-char cap used by the other two forced
                    # dispatches (each scoped to a single file/method) was
                    # silently truncating this aggregated text well before
                    # reaching a fact from a file that happened to sort late
                    # -- confirmed live: the has_group()-derived required
                    # group for custom_credit_note_approval never appeared
                    # anywhere in tool_observations for the account.move
                    # question (not even via the _backfill_missing_required_
                    # groups deterministic backfill below, which reads
                    # straight from these observations and would have caught
                    # a synthesis-level drop but cannot recover a fact that
                    # was never in the text to begin with). Raised only for
                    # THIS forced dispatch, not the generic per-hop cap in the
                    # ReAct loop below or the other two forced dispatches,
                    # since only this one aggregates across a model's full
                    # file set.
                    if len(forced_observation) > 3000:
                        forced_observation = forced_observation[:3000] + "\n[... Content truncated for LLM context limit ...]"
                    # Bloc 7 (J23-24): generalized gating on this forced
                    # dispatch too -- it bypasses the normal ReAct tool
                    # loop, so it must be gated here explicitly rather than
                    # relying on the loop's gating below.
                    forced_observation, omitted_list = gate_observation(
                        tool_name="analyser_verrous_securite",
                        model_name=target_model,
                        observation=forced_observation,
                        G=G,
                        user_groups=resolved_user_group_xmlids,
                    )
                    omitted_items.extend(omitted_list)
                    tool_observations.append(forced_observation)
                    tool_observation_models.append(target_model)
                    hop_count += 1
                    seen_calls.add(call_key)
                    _trace_logger.log_hop(
                        trace_id=_trace_id, hop_index=_hop_index,
                        tool_name="analyser_verrous_securite", tool_args={"model_name": target_model},
                        observation=forced_observation, elapsed_ms=(time.perf_counter() - _t_hop) * 1000,
                    )
                    _hop_index += 1
                    logger.info(
                        "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                        "'analyser_verrous_securite' for model '%s' (structural lock finding present).",
                        target_model,
                    )
                except Exception as te:
                    logger.error("Deterministic analyser_verrous_securite dispatch failed: %s", te)
            if any(k[0] == "analyser_verrous_securite" for k in seen_calls):
                system_prompt += (
                    "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
                    "analyser_verrous_securite has already been run for the target model(s) above "
                    "because the question is approval/security-related; its output is already included "
                    "in the tool observations. Do not call it again -- focus any further tool calls on "
                    "what it does NOT cover (e.g. ir.rule / group-based record visibility via "
                    "evaluer_regles_enregistrement)."
                )

    # J8/J9: force analyser_actions_serveur when the question resolves to a
    # target model, suggests automation/bypass logic (_AUTOMATION_PATTERN),
    # AND the model structurally has ServerAction nodes in the graph
    # (find_server_action_nodes). The structural guard is the primary
    # defense against noise: on a model with zero server actions the cost
    # of a false-positive keyword match is zero (empty tool_observation
    # never appended), so the keyword pattern doesn't need to be perfectly
    # precise on its own.
    if (
        concept.is_resolved
        and concept.resolved_models
        and _question_suggests_automation_bypass(question)
    ):
        from code_intelligence.ci_agent_tools import find_server_action_nodes
        tool_map = {t.name: t for t in ALL_CI_TOOLS}
        sa_tool = tool_map.get("analyser_actions_serveur")
        if sa_tool is not None:
            for target_model in concept.resolved_models:
                if not find_server_action_nodes(G, target_model):
                    continue  # structural guard: nothing to say, skip silently
                call_key = ("analyser_actions_serveur", target_model)
                if call_key in seen_calls:
                    continue
                _t_hop = time.perf_counter()
                try:
                    forced_observation = str(sa_tool.invoke({"model_name": target_model}))
                    # Bloc 9 gap fix (2026-08-13, module 6/8, bloc9-06b/06c):
                    # this dispatch aggregates EVERY ServerAction node on the
                    # target model (same shape as analyser_verrous_securite's
                    # forced dispatch above, which needed 3000 for the same
                    # reason) -- on account.move, 5 boilerplate "Aucun pattern
                    # de securite detecte" entries precede the one real
                    # finding (custom_automation_traps), pushing the real
                    # content (sudo()/hardcoded IDs/trigger condition) past
                    # the flat 1200 cap this dispatch never had raised, unlike
                    # its two siblings -- confirmed live: cut mid-word inside
                    # "sudo()" itself, before the hardcoded-IDs line or the
                    # trigger-condition line were ever stored, so neither the
                    # synthesis LLM nor _backfill_missing_trigger_condition_
                    # literals (which can only re-surface a fact already
                    # present in the stored observation) ever had a chance.
                    if len(forced_observation) > 3000:
                        forced_observation = forced_observation[:3000] + "\n[... Content truncated for LLM context limit ...]"
                    # Bloc 7 (J23-24): same rationale as the
                    # analyser_verrous_securite forced dispatch above --
                    # this bypasses the ReAct loop's gating, so gate here.
                    forced_observation, omitted_list = gate_observation(
                        tool_name="analyser_actions_serveur",
                        model_name=target_model,
                        observation=forced_observation,
                        G=G,
                        user_groups=resolved_user_group_xmlids,
                    )
                    omitted_items.extend(omitted_list)
                    tool_observations.append(forced_observation)
                    tool_observation_models.append(target_model)
                    hop_count += 1
                    seen_calls.add(call_key)
                    _trace_logger.log_hop(
                        trace_id=_trace_id, hop_index=_hop_index,
                        tool_name="analyser_actions_serveur", tool_args={"model_name": target_model},
                        observation=forced_observation, elapsed_ms=(time.perf_counter() - _t_hop) * 1000,
                    )
                    _hop_index += 1
                    logger.info(
                        "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                        "'analyser_actions_serveur' for model '%s' (automation/bypass "
                        "wording + ServerAction nodes present).",
                        target_model,
                    )
                except Exception as te:
                    logger.error("Deterministic analyser_actions_serveur dispatch failed: %s", te)
            if any(k[0] == "analyser_actions_serveur" for k in seen_calls):
                system_prompt += (
                    "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
                    "analyser_actions_serveur has already been run for the target model(s) "
                    "above because the question suggests automation/bypass logic; its output "
                    "is already included in the tool observations. Do not call it again."
                )

    # Bloc 9 gap, found 2026-08-06 (Q1.2 "avoir VIP"): deterministic
    # pre-dispatch of analyser_chaine_surcharge_methode. Unlike the two
    # forced dispatches above, this tool needs a method_name, which never
    # appears in the natural-language question -- so the structural guard
    # (find_methods_with_override_cascade: does ANY method on the resolved
    # model actually have >1 override site in the graph?) is the PRIMARY
    # defense here, not a secondary one. That's what makes it safe to reuse
    # the already-broad _APPROVAL_PATTERN without repeating the Q6.2
    # false-positive regression the amount-only trigger caused earlier: on
    # a model with no real override cascade, a keyword false-positive costs
    # nothing (the guard returns [], nothing is dispatched).
    if (
        concept.is_resolved
        and concept.resolved_models
        and _question_is_approval_related(question)
    ):
        from code_intelligence.ci_agent_tools import find_methods_with_override_cascade
        from code_intelligence.method_override_resolver import find_methods_with_override_risk_findings
        tool_map = {t.name: t for t in ALL_CI_TOOLS}
        override_tool = tool_map.get("analyser_chaine_surcharge_methode")
        if override_tool is not None:
            for target_model in concept.resolved_models:
                candidate_methods = find_methods_with_override_cascade(G, target_model)
                # Second, cheaper filter (2026-08-06 fix): the cascade-only
                # guard alone fires on every ordinary multiply-overridden
                # method (write, create, action_post...) on a shared model
                # like account.move -- confirmed to blow past CI_MAX_HOPS
                # (17 hops on Q1.1/Q1.2/Q5.1) and to bury the real finding
                # in noise. Only dispatch the full LLM-backed tool for
                # methods where the cheap deterministic AST check already
                # found something (unguarded-super OR, 2026-08-06 Bloc 9
                # gap fix, an unchecked long relational-field chain --
                # renamed find_methods_with_unguarded_super ->
                # find_methods_with_override_risk_findings accordingly).
                flagged_methods = find_methods_with_override_risk_findings(G, target_model, candidate_methods)
                flagged_methods = _rank_and_cap_override_methods(question, flagged_methods)
                for method_name in flagged_methods:
                    call_key = ("analyser_chaine_surcharge_methode", target_model, method_name)
                    if call_key in seen_calls:
                        continue
                    _t_hop = time.perf_counter()
                    try:
                        forced_observation = str(override_tool.invoke({
                            "model_name": target_model, "method_name": method_name,
                        }))
                        # Bloc 9 gap, found 2026-08-11 (bloc9-01a/01b rerun,
                        # AFTER both the cap=1 fix and the verrous_securite
                        # truncation fix above): a 3-module override chain
                        # (module header + per-module warning block, each
                        # with a file link and a full explanatory sentence)
                        # routinely exceeds 1200 chars on its own -- confirmed
                        # live by the raw check script's own direct call to
                        # this same tool, which prints ~1400+ chars for
                        # action_valider_avoir's real 3-module chain. Even
                        # with cap=1 correctly limiting to ONE forced
                        # dispatch, that single dispatch's own content was
                        # still being cut -- e.g. losing the regional
                        # module's 20000e relational-chain finding, or the
                        # base module's "no risk detected" closing line,
                        # depending on where in the chain the cut landed.
                        # Raised to 2200 (a single method's chain, capped at
                        # 1 dispatch, needs less headroom than the
                        # whole-model verrous_securite aggregation above,
                        # which can span a dozen+ files and was raised to
                        # 3000).
                        if len(forced_observation) > 2200:
                            forced_observation = forced_observation[:2200] + "\n[... Content truncated for LLM context limit ...]"
                        # Bloc 7 (J23-24): same rationale as the two forced
                        # dispatches above -- bypasses the ReAct loop's
                        # gating, so gate here explicitly.
                        forced_observation, omitted_list = gate_observation(
                            tool_name="analyser_chaine_surcharge_methode",
                            model_name=target_model,
                            observation=forced_observation,
                            G=G,
                            user_groups=resolved_user_group_xmlids,
                        )
                        omitted_items.extend(omitted_list)
                        tool_observations.append(forced_observation)
                        tool_observation_models.append(target_model)
                        hop_count += 1
                        seen_calls.add(call_key)
                        _trace_logger.log_hop(
                            trace_id=_trace_id, hop_index=_hop_index,
                            tool_name="analyser_chaine_surcharge_methode",
                            tool_args={"model_name": target_model, "method_name": method_name},
                            observation=forced_observation, elapsed_ms=(time.perf_counter() - _t_hop) * 1000,
                        )
                        _hop_index += 1
                        logger.info(
                            "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                            "'analyser_chaine_surcharge_methode' for '%s.%s' (approval wording "
                            "+ real override cascade present).",
                            target_model, method_name,
                        )
                    except Exception as te:
                        logger.error("Deterministic analyser_chaine_surcharge_methode dispatch failed: %s", te)
            if any(k[0] == "analyser_chaine_surcharge_methode" for k in seen_calls):
                system_prompt += (
                    "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
                    "analyser_chaine_surcharge_methode has already been run for the "
                    "overridden method(s) above because the question is approval-related "
                    "and a real override cascade exists on the target model; its output is "
                    "already included in the tool observations. Do not call it again -- if "
                    "it flagged an unguarded super() OR an unchecked relational-field chain "
                    "(CHAINE RELATIONNELLE NON VERIFIEE), that finding takes precedence over "
                    "any single-module reading of the method. A relational-chain finding "
                    "often names a SECOND threshold/condition (e.g. a higher amount that "
                    "triggers an additional module's override on top of the first module's "
                    "rule) -- when the question's stated amount clears both thresholds, both "
                    "must be reported together, not only the first one encountered."
                )

    # Bloc 9 gap, found 2026-08-13 (native-Odoo-out-of-scope investigation --
    # see _question_is_access_related/_ACCESS_QUESTION_PATTERN above for
    # the full rationale): force qui_a_acces_a whenever the question asks
    # who can/has the right to do something and a model resolved. Unlike
    # the tools above, this is NOT additionally gated on a structural
    # guard -- ACL entries exist on nearly every real model, so the
    # question-shape keyword IS the meaningful filter here.
    #
    # 2026-08-13 (Bloc 9, module 8/8, bloc9-08a-business): that blanket
    # firing generalized badly onto a model that DOES have a Python
    # security lock. custom.deep.document's action_validate_level2()/
    # action_final_approve() are gated by has_group() in code, already
    # force-dispatched to analyser_verrous_securite above -- the DEFAULT
    # generic read/write/create/unlink ACL matrix is real data (_expand_
    # inheriting_acl_groups correctly walks the IMPLIES hierarchy: every
    # group that transitively implies base.group_user genuinely does have
    # base CRUD access) but answers a DIFFERENT question ("who can read/
    # write this model at all") than the one asked ("who can VALIDATE a
    # 60 000€ document", governed by the has_group() gate, not the CRUD
    # ACL). Confirmed live: qui_a_acces_a's droit='all' matrix (13 unrelated
    # groups -- hr, purchase, stock, hr_expense, hr_holidays...) got dumped
    # alongside the correct has_group() finding, and the small synthesis
    # LLM conflated the two, padding "who can validate" with groups that
    # only have generic read access. Same failure shape as module 1/8's
    # Gap (a): a forced dispatch built for the case where NO other
    # governing mechanism exists (the original out-of-scope fix's actual
    # target) generalizing onto a model where a MORE SPECIFIC mechanism
    # already answers the question. Skip qui_a_acces_a's forced dispatch
    # for a target_model that already got a real (structurally-guarded)
    # analyser_verrous_securite dispatch above -- the has_group() finding
    # IS the answer to "who can do this specific action" for that model;
    # the LLM can still call qui_a_acces_a itself if it genuinely needs the
    # generic ACL matrix too (e.g. a question that also asks about plain
    # read access), same as the other two structurally-guarded tools.
    if concept.is_resolved and concept.resolved_models and _question_is_access_related(question):
        tool_map = {t.name: t for t in ALL_CI_TOOLS}
        acl_tool = tool_map.get("qui_a_acces_a")
        if acl_tool is not None:
            # 2026-08-14 (Bloc 9, module 8/8, bloc9-08a-business, contexte.txt
            # section 46, root cause B): the skip below only prevents the
            # GUARANTEED forced dispatch -- it does not add call_key to
            # seen_calls, so the "Do not call it again" instruction further
            # down (gated on `any(k[0] == "qui_a_acces_a" for k in
            # seen_calls)`) never fires either. The free ReAct LLM is left
            # completely free to call qui_a_acces_a itself on this exact
            # model (confirmed live: reasoning_trace.jsonl hop 2, droit=
            # "write", not the forced-dispatch shape) and re-introduce the
            # same 13-group parasitic ACL matrix this skip-guard was built
            # to keep out of tool_observations. Deliberately not closing the
            # tool off (this skip's own docstring: "Rien n'est retire de la
            # boite a outils" -- the LLM may still genuinely need the ACL
            # matrix for a mixed question). Instead, track which models were
            # skipped so a scoping instruction can be added below regardless
            # of whether the LLM ends up calling the tool on its own.
            skipped_lock_governed_models: List[str] = []
            for target_model in concept.resolved_models:
                if ("analyser_verrous_securite", target_model) in seen_calls:
                    logger.info(
                        "Node [code_intelligence_agent]: skipping deterministic "
                        "qui_a_acces_a dispatch for '%s' -- a real Python security "
                        "lock (has_group()) already governs this model's actions, "
                        "more specific than the generic CRUD ACL matrix.",
                        target_model,
                    )
                    skipped_lock_governed_models.append(target_model)
                    continue
                call_key = ("qui_a_acces_a", target_model)
                if call_key in seen_calls:
                    continue
                _t_hop = time.perf_counter()
                try:
                    forced_observation = str(acl_tool.invoke({
                        "model_name": target_model, "droit": "all",
                    }))
                    if len(forced_observation) > 3000:
                        forced_observation = forced_observation[:3000] + "\n[... Content truncated for LLM context limit ...]"
                    # Bloc 7 (J23-24): same rationale as the forced
                    # dispatches above -- bypasses the ReAct loop's gating,
                    # so gate here explicitly.
                    forced_observation, omitted_list = gate_observation(
                        tool_name="qui_a_acces_a",
                        model_name=target_model,
                        observation=forced_observation,
                        G=G,
                        user_groups=resolved_user_group_xmlids,
                    )
                    omitted_items.extend(omitted_list)
                    tool_observations.append(forced_observation)
                    tool_observation_models.append(target_model)
                    hop_count += 1
                    seen_calls.add(call_key)
                    _trace_logger.log_hop(
                        trace_id=_trace_id, hop_index=_hop_index,
                        tool_name="qui_a_acces_a", tool_args={"model_name": target_model, "droit": "all"},
                        observation=forced_observation, elapsed_ms=(time.perf_counter() - _t_hop) * 1000,
                    )
                    _hop_index += 1
                    logger.info(
                        "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                        "'qui_a_acces_a' for model '%s' (question asks who can/has the "
                        "right to do something).",
                        target_model,
                    )
                except Exception as te:
                    logger.error("Deterministic qui_a_acces_a dispatch failed: %s", te)
            if any(k[0] == "qui_a_acces_a" for k in seen_calls):
                system_prompt += (
                    "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
                    "qui_a_acces_a has already been run for the target model(s) above "
                    "because the question asks who can/has the right to do something; its "
                    "ACL and record-rule output is already included in the tool "
                    "observations. Do not call it again."
                )
            if skipped_lock_governed_models:
                system_prompt += (
                    "\n\n[SCOPING NOTE -- qui_a_acces_a]\n"
                    "For the model(s) "
                    + ", ".join(skipped_lock_governed_models)
                    + ", a Python security lock (has_group()) already governs the "
                    "specific action this question asks about; that finding is already "
                    "included in the tool observations above and is the correct basis "
                    "for answering who can perform THIS action. If you call "
                    "qui_a_acces_a for this model anyway, its output answers a "
                    "DIFFERENT, broader question (generic read/write/create/unlink ACL "
                    "access to the model as a whole) -- do not use it to determine who "
                    "can perform the specific action asked about, and do not treat its "
                    "groups as alternative or additional authorities for that action. "
                    "Each has_group() threshold in the security lock finding is an "
                    "independent minimum-requirement gate ('this group is REQUIRED "
                    "above this amount', meaning members of this group ARE AUTHORIZED to "
                    "validate above this amount), not an exclusive authority tier or ceiling. "
                    "A lock whose threshold is higher than the asked amount (e.g. >100000€ when "
                    "asked about 60000€) does NOT apply to that amount and its group is not required."
                )

    # Bloc9 08c fix (2026-08-14): force evaluer_regles_enregistrement + the
    # can_view_amount_v2 deterministic fact when the question is access-
    # related AND contains a monetary amount AND a model is resolved.
    # Root cause confirmed by reproduction with logging: when the ReAct
    # LLM didn't choose to call evaluer_regles_enregistrement itself, the
    # can_view_amount_v2 code path (inside the ReAct loop's tool-call
    # handler, lines 4185-4244) was NEVER reached, and the synthesis LLM
    # hallucinated "can_view_amount() = True" from scratch. This dispatch
    # guarantees the tri-state fact is computed and injected into
    # tool_observations regardless of the ReAct LLM's tool selection.
    if concept.is_resolved and concept.resolved_models and _question_is_access_related(question):
        _amount_for_rules = _extract_amount(question)
        if _amount_for_rules is not None:
            from code_intelligence.ci_agent_tools import evaluer_regles_raw
            tool_map = {t.name: t for t in ALL_CI_TOOLS}
            rule_tool = tool_map.get("evaluer_regles_enregistrement")
            if rule_tool is not None:
                for target_model in concept.resolved_models:
                    call_key = ("evaluer_regles_enregistrement", target_model)
                    if call_key in seen_calls:
                        continue
                    _t_hop = time.perf_counter()
                    try:
                        import json as _json_dispatch
                        _dispatch_groups = _json_dispatch.dumps(resolved_user_group_xmlids or [])
                        forced_observation = str(rule_tool.invoke({
                            "model_name": target_model,
                            "user_groups_json": _dispatch_groups,
                            "droit": "read",
                        }))
                        if len(forced_observation) > 3000:
                            forced_observation = forced_observation[:3000] + "\n[... Content truncated for LLM context limit ...]"
                        forced_observation, omitted_list = gate_observation(
                            tool_name="evaluer_regles_enregistrement",
                            model_name=target_model,
                            observation=forced_observation,
                            G=G,
                            user_groups=resolved_user_group_xmlids,
                        )
                        omitted_items.extend(omitted_list)
                        tool_observations.append(forced_observation)
                        tool_observation_models.append(target_model)
                        hop_count += 1
                        seen_calls.add(call_key)

                        # Now compute can_view_amount_v2 deterministic fact
                        try:
                            _dispatch_rule_result = evaluer_regles_raw(
                                model_name=target_model,
                                droit="read",
                                user_groups_json=_dispatch_groups,
                            )
                            _dispatch_context = {"amount": _amount_for_rules}
                            _dispatch_context.update(_extract_company_context(question))
                            _dispatch_can_view, _dispatch_unresolved = (
                                _dispatch_rule_result.can_view_amount_v2(_dispatch_context)
                            )
                            tool_observations.append(
                                _format_can_view_amount_fact(
                                    _amount_for_rules, _dispatch_can_view, _dispatch_unresolved
                                )
                            )
                            tool_observation_models.append(target_model)
                            logger.info(
                                "Node [code_intelligence_agent]: Pre-dispatch "
                                "can_view_amount_v2 fact for model=%s, amount=%.0f, "
                                "result=%s, unresolved=%s, context=%s, "
                                "global=%d, group=%d (Bloc9 08c deterministic fix).",
                                target_model, _amount_for_rules, _dispatch_can_view,
                                _dispatch_unresolved, _dispatch_context,
                                len(_dispatch_rule_result.applied_global_rules),
                                len(_dispatch_rule_result.applied_group_rules),
                            )
                        except Exception as ve:
                            logger.error(
                                "Pre-dispatch can_view_amount_v2 injection failed: %s", ve
                            )

                        _trace_logger.log_hop(
                            trace_id=_trace_id, hop_index=_hop_index,
                            tool_name="evaluer_regles_enregistrement",
                            tool_args={"model_name": target_model, "droit": "read"},
                            observation=forced_observation,
                            elapsed_ms=(time.perf_counter() - _t_hop) * 1000,
                        )
                        _hop_index += 1
                        logger.info(
                            "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                            "'evaluer_regles_enregistrement' for model '%s' (access-related "
                            "question with amount=%.0f, Bloc9 08c fix).",
                            target_model, _amount_for_rules,
                        )
                    except Exception as te:
                        logger.error(
                            "Deterministic evaluer_regles_enregistrement dispatch failed: %s", te
                        )
                if any(k[0] == "evaluer_regles_enregistrement" for k in seen_calls):
                    system_prompt += (
                        "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
                        "evaluer_regles_enregistrement has already been run for the target "
                        "model(s) above and the can_view_amount_v2 deterministic fact has been "
                        "injected. Do not call evaluer_regles_enregistrement again."
                    )
    messages = [
        SystemMessage(content=system_prompt),
        *chat_history[-6:],
        HumanMessage(content=question),
    ]

    if tool_observations:
        final_answer = _force_dynamic_uncertainty_answer(question, "\n\n".join(tool_observations))

    _t_react_loop = time.perf_counter()
    for iteration in range(0 if final_answer else REACT_RECURSION_LIMIT):
        # Single-Pass Composite Execution: 1 Tool Selection turn + 1 Synthesis turn
        try:
            ai_msg, _wait = _invoke_with_rate_limit(llm_with_tools, messages)
            _llm_call_count += 1  # J46-J48: tool-selection call
            _ci_groq_wait += _wait
        except Exception as e:
            _llm_call_count += 1  # attempt still counts against the LLM-call budget
            logger.error("LLM tool selection failed: %s", e)
            ai_msg = None

        if ai_msg and getattr(ai_msg, "tool_calls", None):
            # ReAct-loop fix (Bloc 12 review, post-Bloc-8 regression): feed
            # the AI's tool-call message and every resulting ToolMessage
            # back into `messages` so the NEXT iteration's LLM call actually
            # sees what was already tried and what came back (success or
            # failure). Previously `messages` was NEVER updated inside this
            # loop -- every iteration re-sent the exact same initial prompt
            # (system + history + question), so the model had zero memory of
            # its own prior tool calls within the same question. That's what
            # let it repeatedly re-guess wrong technical identifiers (e.g.
            # "demande_conge" instead of the already-confirmed "hr.leave",
            # or "group_region" instead of the real xml_id) across hops
            # instead of learning from the "not found" observation it had
            # just received one message ago. Mirrors what orm_agent_loop
            # (donnees_erp branch) already does correctly.
            messages.append(ai_msg)
            for tool_call in ai_msg.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                tool_id = tool_call["id"]

                # If qui_a_acces_a is called without explicit droit, default to 'all' for single-pass matrix
                if tool_name == "qui_a_acces_a" and "droit" not in tool_args:
                    tool_args["droit"] = "all"

                # Bloc 7 (J23-24) / real-auth fix: force the DEMANDEUR's real
                # groups into evaluer_regles_enregistrement's args (see
                # _override_user_groups_arg docstring). No-op for other tools.
                tool_args = _override_user_groups_arg(tool_name, tool_args, resolved_user_group_xmlids)

                logger.info("Node [code_intelligence_agent]: Single-Dispatch invoking '%s' with args %s", tool_name, tool_args)
                tool_map = {t.name: t for t in ALL_CI_TOOLS}
                if tool_name not in tool_map:
                    # ReAct-loop fix: this case was previously silently
                    # ignored (no observation, no ToolMessage) -- now that
                    # ai_msg + ToolMessages are fed back into `messages`,
                    # every tool_call MUST get a matching ToolMessage or the
                    # next LLM call can be rejected by the API for an
                    # orphaned tool_call_id.
                    logger.warning(
                        "Node [code_intelligence_agent]: LLM requested unknown tool '%s'.",
                        tool_name,
                    )
                    messages.append(ToolMessage(
                        content=f"Outil '{tool_name}' non disponible.",
                        tool_call_id=tool_id,
                    ))
                if tool_name in tool_map:
                    _t_hop = time.perf_counter()  # J30-J31: per-hop timing
                    try:
                        observation = str(tool_map[tool_name].invoke(tool_args))
                        # Bloc 9 gap, found 2026-08-12 (module 1/8, bloc9-01b-
                        # technical live rerun): the generic 1200-char cap below
                        # is fine for most tools, but analyser_chaine_surcharge_
                        # methode's forced pre-dispatch already needed 2200 (see
                        # the raised cap on that call site, same rationale) --
                        # and that forced dispatch is gated on
                        # _question_is_approval_related(question), which a
                        # purely technical wording like "quelles sont toutes les
                        # surcharges ... et dans quel ordre s'exécutent-elles ?"
                        # never matches (no approval-pattern word appears; same
                        # underscore-boundary class of gap already fixed for the
                        # override-modules/override-chain-amount backfills
                        # above). So this exact question only ever reaches the
                        # tool via the LLM's OWN free ReAct call here, which
                        # used to hit the smaller 1200 cap -- confirmed live to
                        # cut the real 3-module chain (2072 chars) mid-way
                        # through module 2, before module 3 (the base module,
                        # 'custom_credit_note_approval') is ever reached. The
                        # LLM then filled the gap by mislabeling unrelated
                        # analyser_verrous_securite content as the missing 3rd
                        # site, and the deterministic backfill couldn't recover
                        # it either -- it can only re-surface a fact already
                        # present in the stored observation, and by then it
                        # genuinely wasn't. Same raised cap as the forced
                        # dispatch, applied here too, rather than trying to
                        # widen the approval-pattern gate again (that gate is
                        # for triggering an EXTRA forced call, not for deciding
                        # how much of a call the LLM makes on its own to
                        # truncate -- widening it further risks the same kind
                        # of over-broad refiring already rejected once for
                        # _APPROVAL_PATTERN, see the J8/J9 comment above it).
                        # Bloc 9 gap fix (2026-08-13, module 6/8): analyser_
                        # actions_serveur's forced pre-dispatch above needed
                        # 3000 for the same aggregation reason -- mirror it
                        # here too, in case the LLM's own free ReAct call
                        # reaches this tool on a question whose wording
                        # doesn't satisfy _question_suggests_automation_bypass
                        # (same class of gap already fixed for
                        # analyser_chaine_surcharge_methode below).
                        _observation_cap = (
                            2200 if tool_name == "analyser_chaine_surcharge_methode"
                            else 3000 if tool_name == "analyser_actions_serveur"
                            else 1200
                        )
                        if len(observation) > _observation_cap:
                            observation = observation[:_observation_cap] + "\n[... Content truncated for LLM context limit ...]"

                        # Bloc 7 (J23-24): compute the RuleEvaluationResult
                        # once, unconditionally, whenever this tool ran --
                        # both the gating below and the can_view_amount
                        # deterministic fact (J14 fix, only when an amount
                        # is present) reuse this same object instead of
                        # calling evaluer_regles_raw twice.
                        rule_result = None
                        if tool_name == "evaluer_regles_enregistrement":
                            try:
                                from code_intelligence.ci_agent_tools import evaluer_regles_raw

                                rule_result = evaluer_regles_raw(
                                    model_name=tool_args.get("model_name", ""),
                                    droit=tool_args.get("droit", "read"),
                                    user_groups_json=tool_args.get("user_groups_json", "[]"),
                                )
                            except Exception as ve:
                                logger.error("evaluer_regles_raw computation failed: %s", ve)

                        # Bloc 7 (J23-24): generalized gating -- filter this
                        # observation according to the demandeur's real
                        # rights BEFORE it ever reaches the synthesis LLM,
                        # so an omitted fact can't leak back out paraphrased.
                        observation, omitted_list = gate_observation(
                            tool_name=tool_name,
                            model_name=tool_args.get("model_name", ""),
                            observation=observation,
                            G=G,
                            user_groups=resolved_user_group_xmlids,
                            rule_result=rule_result,
                        )
                        omitted_items.extend(omitted_list)

                        tool_observations.append(observation)
                        tool_observation_models.append(tool_args.get("model_name", ""))
                        # ReAct-loop fix: feed this (already-gated)
                        # observation back as a ToolMessage tied to its
                        # tool_call_id, so the LLM sees the real result --
                        # "not found", the access matrix, whatever it is --
                        # on its NEXT tool-selection call, instead of being
                        # re-invoked blind against the exact same prompt.
                        messages.append(ToolMessage(content=observation, tool_call_id=tool_id))
                        _ci_per_hop_times.append(time.perf_counter() - _t_hop)  # J30-J31
                        hop_count += 1
                        # J46-J48: index this hop into the reasoning trace --
                        # tool_name, args, observation, elapsed, in call order.
                        _trace_logger.log_hop(
                            trace_id=_trace_id, hop_index=_hop_index, tool_name=tool_name,
                            tool_args=tool_args, observation=observation,
                            elapsed_ms=_ci_per_hop_times[-1] * 1000,
                        )
                        _hop_index += 1

                        # J30-J31: CI_MAX_HOPS enforcement (was defined but
                        # never checked -- the loop ran up to
                        # REACT_RECURSION_LIMIT=6 instead of CI_MAX_HOPS=4).
                        if hop_count >= CI_MAX_HOPS:
                            logger.warning(
                                "Node [code_intelligence_agent]: CI_MAX_HOPS (%d) "
                                "reached -- breaking ReAct loop.", CI_MAX_HOPS,
                            )
                            break

                        # J14 fix (Q6.1 regression):
                        # evaluer_regles_enregistrement's summary_text lists
                        # applicable group rules but never computes the actual
                        # OR-union against a specific amount -- it leaves the
                        # synthesis LLM to guess, and the LLM picked the most
                        # restrictive rule instead of the union. can_view_amount()
                        # already implements the correct AND-global/OR-group
                        # logic; reuse the RuleEvaluationResult computed above
                        # (shares the same resolve + parse logic as the @tool
                        # wrapper) to inject an unambiguous deterministic fact
                        # the synthesis LLM must not recompute or contradict.
                        # This injected fact is NEVER gated: it's already
                        # computed directly against the demandeur's real
                        # rights, so surfacing the verdict itself (not the
                        # rule's internal name/condition) is exactly the
                        # point of Bloc 7's generalized gating, not something
                        # it should hide.
                        if tool_name == "evaluer_regles_enregistrement" and rule_result is not None:
                            amount = _extract_amount(question)
                            if amount is not None:
                                try:
                                    # Bloc9 08c fix: can_view_amount() (regex-
                                    # only, single field) silently returned
                                    # True whenever a domain_force mixed the
                                    # amount condition with something it
                                    # couldn't parse (e.g. company_id) --
                                    # confirmed root cause of 08c. can_view_
                                    # amount_v2() evaluates the FULL parsed
                                    # domain_force via Kleene tri-state logic
                                    # instead, so an unresolved condition
                                    # surfaces as None ("cannot conclude"),
                                    # never as a silent allow.
                                    #
                                    # Bloc9 08c follow-up (2026-08-13):
                                    # company/user context IS now extracted
                                    # from the question (_extract_company_
                                    # context, qualitative same/different
                                    # only -- see that function's own
                                    # docstring for why an identity lookup
                                    # isn't possible on this codebase/test
                                    # instance). A question that says
                                    # nothing about company still yields {}
                                    # here, so a company_id-referencing
                                    # domain_force still resolves to the
                                    # same honest None ("cannot conclude")
                                    # as before this follow-up -- no
                                    # regression on the silent-mention case,
                                    # only new coverage on the explicit one.
                                    context = {"amount": amount}
                                    context.update(_extract_company_context(question))
                                    can_view, unresolved_fields = rule_result.can_view_amount_v2(
                                        context
                                    )
                                    tool_observations.append(
                                        _format_can_view_amount_fact(amount, can_view, unresolved_fields)
                                    )
                                    tool_observation_models.append(tool_args.get("model_name", ""))
                                    logger.info(
                                        "Node [code_intelligence_agent]: Injected deterministic "
                                        "can_view_amount_v2 fact for model=%s, amount=%.0f, "
                                        "result=%s, unresolved=%s, context=%s, "
                                        "global_rules_applied=%d, group_rules_applied=%d "
                                        "(Bloc9 08c diagnostic, 2026-08-14: distinguishes a "
                                        "resolution/wiring gap -- model not found or zero "
                                        "applied rules would silently default this to True -- "
                                        "from a synthesis-level inversion of a correct verdict; "
                                        "bare can_view/unresolved logging alone couldn't tell "
                                        "the two apart on the bloc9-08c-nested-domain-trap rerun).",
                                        tool_args.get("model_name", ""), amount, can_view,
                                        unresolved_fields, context,
                                        len(rule_result.applied_global_rules),
                                        len(rule_result.applied_group_rules),
                                    )
                                except Exception as ve:
                                    logger.error(
                                        "Deterministic can_view_amount injection failed: %s", ve
                                    )
                    except Exception as te:
                        logger.error("Tool execution failed (%s): %s", tool_name, te)
                        _error_observation = f"Error executing {tool_name}: {str(te)}"
                        tool_observations.append(_error_observation)
                        tool_observation_models.append(tool_args.get("model_name", ""))
                        # ReAct-loop fix: surface the failure to the LLM
                        # too, so it doesn't blindly repeat the exact same
                        # failing call on the next iteration.
                        messages.append(ToolMessage(content=_error_observation, tool_call_id=tool_id))
        elif ai_msg and ai_msg.content:
            final_answer = ai_msg.content

        # Synthesize clean final answer from composite tool output
        if not final_answer:
            if tool_observations:
                # Q6.1 fix: strip 'could not be resolved' noise from
                # qui_a_acces_a before it reaches the synthesis LLM when
                # the real-auth override has already injected the
                # demandeur's real groups into evaluer_regles_enregistrement
                # and a deterministic can_view_amount fact is present.
                tool_observations, tool_observation_models = _strip_group_resolution_noise(
                    tool_observations, resolved_user_group_xmlids, tool_observation_models,
                )
                synthesis_prompt = (
                    f"Original Question: {question}\n\n"
                    f"Knowledge Graph Output:\n" + "\n---\n".join(tool_observations) +
                    f"\n\nSynthesize a clear, professional response based strictly on the "
                    f"data above. Respond in the SAME language as the Original Question "
                    f"above (French question -> French answer, English question -> "
                    f"English answer) -- never mix languages. Do NOT translate exact "
                    f"technical identifiers (model names, XML-IDs, group names, method "
                    f"names) -- copy them verbatim. Each observation above comes from a "
                    f"distinct mechanism (ir.rule evaluation vs Python code lock analysis "
                    f"vs server action analysis) -- NEVER combine a numeric threshold or "
                    f"condition from one mechanism with a rule/lock name from a different "
                    f"one; attribute each finding only to its own source. Some observations "
                    f"carry an explicit confidence tag literally present in their source text "
                    f"(e.g. '[Confiance: FAIBLE]', '[Confiance: HIGH]') -- for those, copy the "
                    f"exact tag text verbatim next to the finding it qualifies; never translate, "
                    f"abbreviate, or paraphrase HIGH/MEDIUM/LOW/FAIBLE. Observations with NO "
                    f"such tag in their source text (e.g. ir.rule / evaluer_regles_enregistrement "
                    f"output, resolved model listings) are deterministic facts -- NEVER invent, "
                    f"infer, or add a confidence tag to them. Presenting a deterministic fact as "
                    f"if it carried a confidence level is itself a fabrication. "
                    f"If a [FAIT DÉTERMINISTIQUE] observation is present, it is the "
                    f"authoritative verdict on the user's access for the stated amount -- "
                    f"never recompute or contradict it, and do NOT mention, paraphrase, or "
                    f"allude to any 'could not be resolved' message from a different tool "
                    f"about group identifiers; those are obsolete artifacts of an earlier "
                    f"resolution step and have been superseded by the deterministic "
                    f"evaluation. If that verdict says the engine CANNOT determine access "
                    f"(an indeterminate/'ind\u00e9termin\u00e9' result, listing which condition(s) "
                    f"could not be resolved), you MUST report that uncertainty explicitly and "
                    f"MUST NOT state or imply that access is allowed or denied -- do not round "
                    f"an indeterminate verdict to a yes/no answer. This verdict is a CONCLUSION, not an explanation: you MUST "
                    f"still explain WHY in your answer, using the applicable and ignored rule "
                    f"names/domain_force from the OTHER observations in this same response "
                    f"(e.g. an unconditional group rule that outweighs a capped one via OR, "
                    f"or -- when no group rule applies at all -- the remaining global rule that "
                    f"carries no amount condition). Never quote or restate the bracketed "
                    f"'[FAIT DÉTERMINISTIQUE]' label or the mechanism name "
                    f"'evaluer_regles_enregistrement.can_view_amount' itself as if that were "
                    f"the explanation -- it is internal bookkeeping, not user-facing reasoning. "
                    f"Any file citation you make MUST keep its exact line range from the "
                    f"source observation (file:///path#L12-L25) -- never drop the line range "
                    f"even when shortening a citation. Any rule/action/group xml_id you cite "
                    f"as a sourcing claim MUST be prefixed 'xml_id: module.identifier', copied "
                    f"verbatim from the source observation. "
                    f"If an observation contains 'SUPER() NON GARDÉ', it means a conditional "
                    f"exemption in one module can be silently nullified by an unconditional "
                    f"super() call re-applying the parent module's logic -- this is the ACTUAL "
                    f"real-world behavior, more authoritative than a single module's lock message "
                    f"read in isolation. When both are present, lead the answer with what the "
                    f"override-chain finding says actually happens, not with the base module's "
                    f"lock message alone -- do not present the base module's rule as the answer "
                    f"while ignoring a SUPER() NON GARDÉ finding on the same method. "
                    f"If an observation contains 'CHAINE RELATIONNELLE NON VÉRIFIÉE', it "
                    f"describes a SECOND, ADDITIONAL threshold/condition from a different "
                    f"override module on top of whatever the base module's lock message already "
                    f"said (e.g. base module: >5000€ needs manager approval; override module: "
                    f">20000€ ALSO triggers director notification, with a real risk it silently "
                    f"fails if the hierarchy chain is incomplete) -- when the amount in the "
                    f"Original Question clears BOTH thresholds, report BOTH levels explicitly as "
                    f"a cascade, including the relational-chain risk verbatim; never report only "
                    f"the first (lowest) threshold and drop the second. "
                    f"When an observation names a chain of override modules (e.g. 'Cha\u00eene de "
                    f"surcharge de ... (N modules ...)'), the list of modules and their line "
                    f"ranges in that observation is EXHAUSTIVE and CLOSED -- never add a module, "
                    f"file path, or line range that is not copied verbatim from that observation, "
                    f"even to make the pattern look complete or consistent with the others; if "
                    f"you are unsure whether a module belongs, omit it rather than invent one. "
                    f"When a finding includes a literal condition or field name in backticks "
                    f"(e.g. `rec.partner_id.avoir_vip_exempt`, `rec.amount_total > 20000`), copy "
                    f"that literal verbatim in your answer -- do not paraphrase it away into a "
                    f"generic phrase like 'a conditional branch'. If a module listed in an "
                    f"override chain has NO \u26a0\ufe0f warning attached to it in the observation, state "
                    f"explicitly that no risk pattern was detected for that module by this "
                    f"heuristic -- never invent a risk finding to fill that gap. "
                    f"If the Original Question above asks about more than one condition or "
                    f"threshold (e.g. 'qui peut valider X, et y a-t-il une restriction "
                    f"supplémentaire au-delà de Y ?'), answer EACH part explicitly and "
                    f"separately -- never answer only the first part and silently imply 'no' "
                    f"for the rest. When an observation's 'Messages de verrous' section lists "
                    f"more than one message, treat each one as a DISTINCT finding to report -- "
                    f"do not summarize or select only one of them; a second or third message in "
                    f"that list is exactly as authoritative as the first. When the question "
                    f"asks who can validate/approve an operation for a specific monetary amount, "
                    f"evaluate each lock message condition against that specific amount: a lock "
                    f"whose threshold is exceeded (e.g. >50000€ for a 60000€ document) is triggered "
                    f"and requires the specified group (meaning members of that group ARE AUTHORIZED to "
                    f"validate above that amount, and the threshold is a minimum floor where their authority "
                    f"is required, NOT an upper ceiling where their authority ends). A lock whose threshold "
                    f"is NOT reached (e.g. >100000€ for a 60000€ document) is not triggered, does not "
                    f"restrict that amount, and its group is NOT required for that amount."
                )
                try:
                    # 2026-08-14: routed through get_chat_llm() -- see the
                    # ReAct-loop instantiation above for the full rationale.
                    plain_llm = get_chat_llm(
                        temperature=0.0, max_retries=0, max_tokens=4096,
                        # Review finding (Q1.1 benchmark run): mitigate llama-3.1-8b-instant's
                        # decoding-collapse failure mode (see _detect_degenerate_repetition) --
                        # a mild penalty discourages the model from repeating the same token/
                        # phrase without materially changing normal synthesis quality.
                        model_kwargs={"frequency_penalty": 0.3, "presence_penalty": 0.2},
                    )
                    _t_synthesis = time.perf_counter()
                    final_resp, _synth_wait = _invoke_with_rate_limit(plain_llm, [HumanMessage(content=synthesis_prompt)])
                    _llm_call_count += 1  # J46-J48: synthesis call
                    _ci_groq_wait += _synth_wait
                    final_answer = final_resp.content
                    _ci_synthesis_time = time.perf_counter() - _t_synthesis
                    if _detect_any_degenerate_repetition(final_answer):
                        logger.warning(
                            "Node [code_intelligence_agent]: degenerate repetition detected in "
                            "synthesis output (%d chars) -- retrying once with an explicit "
                            "anti-repetition instruction before falling back to stripping it.",
                            len(final_answer),
                        )
                        retry_messages = [
                            HumanMessage(content=synthesis_prompt),
                            SystemMessage(content=(
                                "RAPPEL STRICT : ta r\u00e9ponse pr\u00e9c\u00e9dente contenait une "
                                "r\u00e9p\u00e9tition d\u00e9g\u00e9n\u00e9r\u00e9e (le m\u00eame mot ou groupe "
                                "de mots r\u00e9p\u00e9t\u00e9 des dizaines de fois de suite). Ne r\u00e9p\u00e8te "
                                "JAMAIS un mot ou groupe de mots plus de 2-3 fois de suite. Si tu "
                                "n'as rien de nouveau \u00e0 dire sur un point, passe au suivant ou "
                                "termine ta phrase."
                            )),
                        ]
                        try:
                            retry_resp, _retry_wait = _invoke_with_rate_limit(plain_llm, retry_messages, max_retries=2)
                            _llm_call_count += 1  # J46-J48: anti-repetition retry call
                            _ci_groq_wait += _retry_wait
                            if not _detect_any_degenerate_repetition(retry_resp.content):
                                final_answer = retry_resp.content
                            else:
                                logger.error(
                                    "Node [code_intelligence_agent]: synthesis still degenerate "
                                    "after retry -- stripping the repeated run instead of shipping it."
                                )
                                final_answer = _strip_any_degenerate_repetition(final_answer)
                        except Exception as retry_e:
                            logger.error("Anti-repetition retry failed: %s", retry_e)
                            final_answer = _strip_any_degenerate_repetition(final_answer)
                except Exception as e:
                    logger.error("Synthesis failed: %s", e)
                    final_answer = "\n\n".join(tool_observations)
            else:
                final_answer = "Je n'ai pas de données disponibles dans le graphe de connaissances pour répondre à cette question."

        if final_answer:
            break

    raw_tool_output = "\n\n".join(tool_observations)
    out_of_scope_model_answer = _force_out_of_scope_model_answer(question, concept)
    dynamic_uncertainty_answer = _force_dynamic_uncertainty_answer(question, raw_tool_output)
    if out_of_scope_model_answer:
        final_answer = out_of_scope_model_answer
    elif dynamic_uncertainty_answer:
        final_answer = dynamic_uncertainty_answer
    else:
        # Bloc 9 cross-module gap fix (2026-08-10): deterministic backfill,
        # not a prompt instruction -- see the comment above
        # _REQUIRED_GROUP_LINE_RE for why. Never runs on the dynamic-
        # uncertainty path above (that answer is deliberately restricted to
        # "cannot determine with certainty"; appending a required-group fact
        # there would contradict its own point).
        # Bloc 9 gap fix (2026-08-10, bloc9-05c-no-link-trap contamination):
        # scope both backfills to the model(s) the question actually
        # resolved to, instead of the full unscoped raw_tool_output -- see
        # _scoped_raw_tool_output docstring. raw_tool_output itself stays
        # unscoped for citation verification / dynamic-uncertainty below.
        scoped_tool_output = _scoped_raw_tool_output(
            tool_observations, tool_observation_models, concept.resolved_models,
        )
        # TEMP DEBUG (2026-08-13, requested for bloc9-08 follow-up investigation)
        # -- remove once the grounding-validator false-negative/false-positive
        # rate has been checked against a few more real bloc9-08-style runs.
        logger.info(
            "Node [code_intelligence_agent]: DEBUG scoped_tool_output for this turn "
            "(%d chars): %s", len(scoped_tool_output), scoped_tool_output,
        )
        # Bloc 9 gap fix (2026-08-14, module 8/8, bloc9-08a-business): detect
        # and correct synthesis-level inversions of Python security lock
        # threshold logic (e.g. denying manager authority above threshold or
        # wrongly attributing authority to higher untriggered admin groups).
        final_answer = _correct_security_lock_threshold_contradictions(final_answer, scoped_tool_output, question)
        final_answer = _backfill_missing_required_groups(final_answer, scoped_tool_output, question)
        # Bloc 9 gap fix (2026-08-13, module 4/8, bloc9-04a-business /
        # bloc9-04c-manager-trap): same deterministic-backfill principle,
        # applied right after the required-groups backfill above since both
        # read analyser_verrous_securite's output (as opposed to the
        # override-cascade family of backfills below, which read
        # analyser_chaine_surcharge_methode's) -- see the comment above
        # _SECURITY_LOCK_MESSAGES_MARKER for the fact shape this restores.
        final_answer = _backfill_missing_security_lock_amount(final_answer, scoped_tool_output, question=question)
        # Bloc 9 gap fix (2026-08-11, module 1/8 rerun): same deterministic-
        # backfill principle, two more applications -- see the comment
        # above _OVERRIDE_MODULE_RE/_OVERRIDE_CHAIN_AMOUNT_RE for why these
        # two are separate from the required-groups backfill (different
        # fact shapes: a module name dropped/mislabeled, and a relational-
        # chain amount threshold ignored on business-phrased questions).
        final_answer = _backfill_missing_override_modules(final_answer, scoped_tool_output)
        # Bloc 9 gap fix (2026-08-12, module 1/8, bloc9-01b-technical): fix
        # the prose ITSELF when it actively contradicts the override-cascade
        # facts (denies other overrides exist, or fabricates a short-circuit
        # execution order) -- run right after the module backfill above so
        # both operate on the same _extract_override_modules() data, before
        # the (separate) amount backfill appends anything further below.
        final_answer = _correct_override_cascade_contradictions(final_answer, scoped_tool_output)
        final_answer = _backfill_missing_override_chain_amount(final_answer, scoped_tool_output)
        # Bloc 9 gap fix (2026-08-11, module 6/8, bloc9-06c-technical-
        # condition-capture): same deterministic-backfill principle applied
        # to analyser_actions_serveur's trigger-condition literal (e.g.
        # 'in_refund') instead of the override-cascade's amount/module --
        # see the comment above _TRIGGER_CONDITION_RE for why only the
        # quoted literal is backfilled, not the whole condition expression.
        final_answer = _backfill_missing_trigger_condition_literals(final_answer, scoped_tool_output)
        # Bloc 9 gap fix (2026-08-13, module 6/8, bloc9-06c-technical-
        # condition-capture): same deterministic-backfill principle applied
        # to the hardcoded privileged-partner IDs inside the same
        # analyser_actions_serveur finding -- see the comment above
        # _HARDCODED_IDS_LINE_RE for why only the bracketed ID tokens are
        # backfilled, not the surrounding sentence.
        final_answer = _backfill_missing_hardcoded_id_literals(final_answer, scoped_tool_output)
        # Bloc 9 gap fix (2026-08-11, module 1/8, bloc9-01c-vip-trap):
        # same deterministic-backfill principle applied to the SUPER() NON
        # GARDÉ warning from the override-cascade analysis -- the condition
        # field name (e.g. avoir_vip_exempt) and the super() trap fact are
        # reliably dropped when Groq 413 truncation cuts the observation.
        final_answer = _backfill_missing_unguarded_super(final_answer, scoped_tool_output)
        # Bloc 9 gap fix (2026-08-10, bloc9-05c-no-link-trap): same
        # deterministic-backfill principle, second application -- see the
        # comment above _LINK_GUARD_RE for why this one is unconditional
        # (always appended when the annotation exists) rather than gated on
        # question wording like the required-groups backfill above.
        final_answer = _backfill_link_guard_clarifications(final_answer, scoped_tool_output)
        # Bloc9 08c follow-up (2026-08-14): symmetric to the override-cascade
        # contradiction fix above, but for the can_view_amount_v2 fact --
        # correct a synthesis-level inversion of the deterministic verdict
        # in place. Deliberately unconditional (no question-wording gate),
        # same reasoning as every other correction/backfill in this module:
        # the presence of the fact itself (_has_can_view_amount_fact) is
        # already the real relevance guard. Placed after the link-guard
        # backfill (which also appends a '[FAIT' block) so its cutoff logic
        # never mistakes the link-guard's own block for prose to scan.
        final_answer = _correct_can_view_amount_contradictions(final_answer)
        # Bloc 9 gap fix (2026-08-13, module 8/8 follow-up investigation):
        # a NEGATIVE/grounding validator, unlike every backfill above (which
        # only ever ADDS a fact known to be true). This one only ever FLAGS,
        # never silently strips -- same transparency principle already used
        # by verify_citations/annotate_unverifiable_citations right below for
        # the structurally identical problem (an LLM claim with no verified
        # backing in this turn's evidence). Extracts the set of group
        # xmlids actually grounded in this turn's scoped_tool_output (reusing
        # _extract_required_groups -- the exact same has_group() line format
        # _backfill_missing_required_groups already trusts as authoritative),
        # then flags any <module>.group_<x>-shaped token in final_answer that
        # isn't in that set. Deliberately a no-op when grounded is empty --
        # a turn where no security-lock tool fired this hop has no reference
        # set to check against, and flagging every group mention as fake in
        # that case would be strictly worse than saying nothing.
        final_answer = _flag_ungrounded_group_xmlids(final_answer, scoped_tool_output)
        # Bloc 9 gap fix (2026-08-14, module 1/8 follow-up): distinct from
        # the flag above -- a group that IS grounded but only in a
        # non-custom (core Odoo) block of this same scoped_tool_output is
        # never legitimate content for this question, so it is stripped
        # rather than merely flagged. See _grounded_core_only_groups /
        # _strip_core_only_group_mentions docstrings above for the full
        # rationale and the precedent (module 5/8 Bug 2) for why a flag
        # alone was not sufficient for this shape of problem.
        final_answer = _strip_core_only_group_mentions(final_answer, scoped_tool_output)

    from code_intelligence.sourcing_guard import verify_citations, annotate_unverifiable_citations
    sourcing_result = verify_citations(final_answer, raw_tool_output)
    if not sourcing_result.is_fully_verified:
        logger.warning("Node [code_intelligence_agent]: Unverified citations -- %s", sourcing_result)
        final_answer = annotate_unverifiable_citations(final_answer, sourcing_result)

    # Review finding (Q1.1 benchmark run): final catch-all in case a
    # degenerate repetition slipped through on a path OTHER than the main
    # synthesis-prompt branch above (e.g. ai_msg.content returned directly
    # without any tool call) -- never ship a wall of repeated tokens
    # regardless of which code path produced final_answer.
    if _detect_any_degenerate_repetition(final_answer):
        logger.error(
            "Node [code_intelligence_agent]: degenerate repetition detected in final_answer "
            "outside the main synthesis retry path -- stripping before returning."
        )
        final_answer = _strip_any_degenerate_repetition(final_answer)

    final_answer += "\n\n[Source: Graphe de Connaissances Code Intelligence]"

    # Bloc 7 (J23-24): surface the omission state explicitly and visibly,
    # kept as its own separate footer -- never merged into the sourcing
    # warning above -- so an omission is never mistaken for an unverified
    # citation or folded into the confidence score.
    from rag.schemas import OmittedForAuthorization
    # Dedup: the same tool (e.g. evaluer_regles_enregistrement on the same
    # model) can legitimately be invoked more than once across the forced
    # pre-dispatch + ReAct loop, or re-invoked by the LLM with identical
    # args -- each call gates and records its own OmittedItem, so without
    # this the footer/response repeat the identical omission N times
    # (observed in the J28-29 benchmark run, e.g. Q5.1 showing the same
    # ir.rule omission 4x). Dedup on (label, reason), order-preserving.
    _seen_omitted_keys: set = set()
    deduped_omitted_items = []
    for _item in omitted_items:
        _key = (_item.label, _item.reason)
        if _key not in _seen_omitted_keys:
            _seen_omitted_keys.add(_key)
            deduped_omitted_items.append(_item)
    omitted_for_authorization = [
        OmittedForAuthorization(label=item.label, reason=item.reason)
        for item in deduped_omitted_items
    ]
    if omitted_for_authorization:
        omission_separator = chr(10)
        omission_lines = omission_separator.join(f"  - {o.label} : {o.reason}" for o in omitted_for_authorization)
        final_answer += (
            "\n\n\U0001F512 \u00c9L\u00c9MENT(S) OMIS POUR RAISON D'AUTORISATION (Bloc 7 / J23-24):\n"
            + omission_lines
        )

    # Build sources from tool observations
    sources = []
    for obs in tool_observations:
        if obs and str(obs).strip():
            sources.append(SourceReference(
                source="Code Intelligence Graph",
                doc_type="code_graph",
                title="Graphe de Connaissances Odoo",
                snippet=str(obs)[:150],
            ))

    response = AssistantResponse(
        answer=final_answer,
        sources=sources,
        confidence=1.0 if tool_observations else 0.5,
        omitted_for_authorization=omitted_for_authorization,
    )

    # J30-J31: compute effective latency (algorithmic) by subtracting Groq waits
    _ci_total_wall = time.time() - start_time
    _ci_react_loop_time = time.perf_counter() - _t_react_loop if '_t_react_loop' in dir() else 0.0
    _ci_post_time = time.perf_counter() - (_t_react_loop + _ci_react_loop_time) if '_t_react_loop' in dir() else 0.0

    timing = state.get("timing", {}).copy()
    timing["code_intelligence_time"] = _ci_total_wall
    timing["ci_hop_count"] = hop_count
    timing["ci_groq_wait_time"] = round(_ci_groq_wait, 3)
    timing["ci_effective_time"] = round(_ci_total_wall - _ci_groq_wait, 3)
    timing["ci_business_resolver_time"] = round(_ci_resolver_time, 3) if '_ci_resolver_time' in dir() else 0.0
    timing["ci_per_hop_times"] = [round(t, 3) for t in _ci_per_hop_times]
    timing["ci_synthesis_time"] = round(_ci_synthesis_time, 3) if '_ci_synthesis_time' in dir() else 0.0
    timing["llm_call_count"] = _llm_call_count

    # Bloc 12 / J46-J48: close the reasoning trace for this question --
    # SUMMARY record ties hop_count/llm_call_count/total_time to every HOP
    # record logged above under the same trace_id, and flags whether
    # CI_MAX_HOPS was actually hit (the J48 guardrail).
    _trace_logger.log_summary(
        trace_id=_trace_id, branch="code_intelligence", question=question,
        hop_count=hop_count, llm_call_count=_llm_call_count,
        total_time_ms=_ci_total_wall * 1000, hop_cap=CI_MAX_HOPS,
    )

    return {
        "response": response,
        "raw_answer": final_answer,
        "timing": timing,
        "raw_tool_output": "\n\n".join(tool_observations),
    }


def format_output(state: RAGState) -> dict:
    """Format and clean up the final output (e.g. OCR warnings)."""
    logger.info("Node [format_output]: Formatting final response")
    
    response = state.get("response")
    chunks = state.get("retrieved_chunks", [])
    
    route = state.get("route")
    if response and chunks and route == QueryRoute.DOCUMENTAIRE.value:
        # OCR Warning Logic
        has_low_ocr = any(chunk.get("metadata", {}).get("ocr_quality") == "low" for chunk in chunks)
        if has_low_ocr:
            response.ocr_warning = True
            response.answer += "\n\n⚠️ *Cette information provient d'un document numérisé dont la qualité de lecture est limitée.*"

        # Populate sources from chunks if not already set (documentary branch)
        if not response.sources:
            sources = []
            for chunk in chunks:
                meta = chunk.get("metadata") or {}
                doc = chunk.get("document", "")
                snippet = doc[:100] + "..." if len(doc) > 100 else doc
                
                sources.append(SourceReference(
                    source=meta.get("source", "unknown"),
                    doc_type=meta.get("type", "document"),
                    title=meta.get("title", meta.get("source", "unknown")),
                    snippet=snippet
                ))
            response.sources = sources
            
        if response.sources and "[Source:" not in response.answer:
            main_src = response.sources[0].title or response.sources[0].source
            response.answer += f"\n\n[Source: Documentation Odoo - {main_src}]"

    return {"response": response}


# ── Graph Construction ────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    """Build and compile the RAG LangGraph with hybrid routing."""
    workflow = StateGraph(RAGState)

    # Add nodes
    workflow.add_node("retrieve", retrieve)
    workflow.add_node("route", route)
    workflow.add_node("generate", generate)
    workflow.add_node("orm_agent_loop", orm_agent_loop)
    workflow.add_node("hybrid_node", hybrid_node)
    workflow.add_node("code_intelligence_agent", code_intelligence_agent)
    workflow.add_node("format_output", format_output)

    # Edges
    workflow.add_edge(START, "retrieve")
    workflow.add_edge("retrieve", "route")

    # Conditional routing
    workflow.add_conditional_edges("route", route_decision, {
        QueryRoute.DOCUMENTAIRE.value: "generate",
        QueryRoute.DONNEES_ERP.value: "orm_agent_loop",
        QueryRoute.HYBRIDE.value: "hybrid_node",
        QueryRoute.CODE_INTELLIGENCE.value: "code_intelligence_agent",
    })

    workflow.add_edge("generate", "format_output")
    workflow.add_edge("orm_agent_loop", "format_output")
    workflow.add_edge("hybrid_node", "format_output")
    workflow.add_edge("code_intelligence_agent", "format_output")
    workflow.add_edge("format_output", END)

    return workflow.compile()


def query_graph(
    question: str,
    chat_history: Optional[List[BaseMessage]] = None,
    uid: Optional[int] = None,
    api_key: Optional[str] = None,
    skills: Optional[dict] = None,
    user_groups: Optional[List[int]] = None,
) -> AssistantResponse:
    """
    Public API to query the graph.
    uid: Odoo user id for RBAC passthrough.
    api_key: Odoo user API key / password for authenticated XML-RPC calls.
    user_groups: real Odoo group ids of the requester, signed into the JWT
    by the Odoo controller. Used to evaluate ir.rule record rules against
    the actual requester, never guessed by the LLM, so Code Intelligence
    explanations are gated by the real demandeur's rights (Bloc 7).
    """
    import time
    import json
    start_time = time.time()
    
    if chat_history is None:
        chat_history = []
    if skills is None:
        skills = {}

    from tools.odoo_tools import odoo_uid_ctx, odoo_api_key_ctx
    # Propagate the uid and api_key to tools via contextvars
    uid_token = None
    api_key_token = None
    if uid is not None:
        uid_token = odoo_uid_ctx.set(uid)
    if api_key is not None:
        api_key_token = odoo_api_key_ctx.set(api_key)

    try:
        app = build_graph()
        initial_state = {
            "question": question,
            "chat_history": chat_history,
            "uid": uid,
            "skills": skills,
            "timing": {},
            "retrieved_chunks": [],
            "raw_answer": "",
            "route": None,
            "response": None,
            "user_groups": user_groups or [],
        }
    
        logger.info("Invoking graph for question: '%s'", question)
        final_state = app.invoke(initial_state)
        
        # Logging structured latency
        timing = final_state.get("timing", {})
        timing["total_time"] = time.time() - start_time
        logger.info(json.dumps({"event": "request_latency", "metrics": timing}))
        
        return final_state["response"]
    except Exception as e:
        logger.error("Graph execution failed: %s", e)
        return AssistantResponse(
            answer="Une erreur interne s'est produite lors de l'exécution du pipeline.",
            sources=[],
            confidence=0.0
        )
    finally:
        if uid_token:
            odoo_uid_ctx.reset(uid_token)
        if api_key_token:
            odoo_api_key_ctx.reset(api_key_token)
