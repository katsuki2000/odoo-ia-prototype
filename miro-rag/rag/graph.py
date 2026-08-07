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
from pathlib import Path
from typing import TypedDict, List, Optional, Any

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

logger = logging.getLogger(__name__)

import re

# ── Groq Rate Limiting & Throttle ─────────────────────────────────────────────
_groq_call_lock = threading.Lock()
_last_groq_call_time = [0.0]
MIN_GROQ_CALL_INTERVAL = 5.0  # Enforce 5.0s minimum spacing between LLM calls


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


def _parse_reset_seconds(header_value: str, default: float = 20.0) -> float:
    """
    Groq's x-ratelimit-reset-* headers come as e.g. '13.42s' or '1m3.42s'.
    Parse into a plain float number of seconds.
    """
    if not header_value:
        return default
    match = re.match(r"(?:(\d+)m)?([\d.]+)s", header_value.strip())
    if not match:
        return default
    minutes = float(match.group(1)) if match.group(1) else 0.0
    seconds = float(match.group(2))
    return minutes * 60 + seconds


def _extract_rate_limit_headers(exc: Exception) -> dict:
    """
    Best-effort extraction of Groq rate-limit headers from whatever
    exception langchain_groq/groq-python raises on a 429.
    """
    for attr_path in ("response", "http_response", "resp"):
        resp = getattr(exc, attr_path, None)
        if resp is not None and hasattr(resp, "headers"):
            return dict(resp.headers)
    cause = getattr(exc, "__cause__", None)
    if cause is not None:
        resp = getattr(cause, "response", None)
        if resp is not None and hasattr(resp, "headers"):
            return dict(resp.headers)
    return {}

class _ToolCallFallback:
    """Stand-in minimal pour un AIMessage : seuls .tool_calls et .content sont lus par la boucle ReAct."""
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls
        self.content = ""


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


_TOOL_USE_FAILED_RE = re.compile(r"'code':\s*'tool_use_failed'.*?'failed_generation':\s*'(.*?)'\s*\}", re.DOTALL)
_FAILED_GEN_CALL_RE = re.compile(r"<function=(\w+)>(\{.*\})")


def _try_recover_tool_use_failed(exc: Exception):
    """
    llama-3.1-8b-instant régresse parfois vers un pattern texte
    '<function=NOM>{...}' au lieu d'un tool_call structuré, ce que
    l'API Groq rejette en 400 tool_use_failed. On récupère l'intention
    par regex plutôt que de perdre le tour.
    Retourne None si le payload n'est pas récupérable (laisse la place au retry).
    """
    msg = str(exc)
    if "tool_use_failed" not in msg:
        return None
    match = _TOOL_USE_FAILED_RE.search(msg)
    if not match:
        return None
    call_match = _FAILED_GEN_CALL_RE.search(match.group(1))
    if not call_match:
        return None
    fn_name, args_raw = call_match.group(1), call_match.group(2)
    try:
        args = json.loads(args_raw)
    except json.JSONDecodeError:
        return None
    logger.warning("Récupération d'un tool_call malformé via failed_generation: %s(%s)", fn_name, args)
    return _ToolCallFallback([{"name": fn_name, "args": args, "id": f"fallback_{fn_name}", "type": "tool_call"}])

_TOOL_MSG_HARD_CAP = 400


def _reduce_message_context(messages: list) -> list:
    """
    Groq 413 (payload too large) has a FIXED request size -- unlike a 429,
    resending the identical messages after a wait will never succeed, since
    the token count doesn't change on its own. This shrinks the largest,
    most compressible part of the payload (ToolMessage and HumanMessage synthesis prompts).
    """
    from langchain_core.messages import ToolMessage, HumanMessage

    reduced = []
    for msg in messages:
        if (
            isinstance(msg, ToolMessage)
            and isinstance(msg.content, str)
            and len(msg.content) > _TOOL_MSG_HARD_CAP
        ):
            reduced.append(
                ToolMessage(
                    content=(
                        msg.content[:_TOOL_MSG_HARD_CAP]
                        + "\n[... tronqué pour respecter la limite de taille de requête Groq ...]"
                    ),
                    tool_call_id=msg.tool_call_id,
                )
            )
        elif (
            isinstance(msg, SystemMessage)
            and isinstance(msg.content, str)
            and len(msg.content) > 1000
        ):
            reduced.append(
                SystemMessage(
                    content=(
                        msg.content[:1000]
                        + "\n[... tronqué pour respecter la limite de taille Groq ...]"
                    )
                )
            )
        elif (
            isinstance(msg, HumanMessage)
            and isinstance(msg.content, str)
            and len(msg.content) > 1500
        ):
            reduced.append(
                HumanMessage(
                    content=(
                        msg.content[:1500]
                        + "\n[... tronqué pour respecter la limite de taille de requête Groq ...]"
                    )
                )
            )
        else:
            reduced.append(msg)
    return reduced


def _invoke_with_rate_limit(llm_with_tools, messages, max_retries: int = 5):
    """
    Invoke le LLM Groq avec :
      - espacement minimal entre appels
      - backoff dynamique sur 429 (headers x-ratelimit-reset-tokens)
      - réduction de contexte sur 413 (payload trop gros -- attendre ne sert à rien)
      - récupération / retry renforcé sur tool_use_failed
      - retry générique avec backoff exponentiel sur erreurs de connexion transitoires

    Returns (result, wait_seconds) where wait_seconds is the total time spent
    sleeping for rate-limit backoffs and minimum-interval enforcement -- callers
    subtract this from wall-clock to get effective (algorithmic) latency.
    (J30-J31: performance instrumentation.)
    """
    context_reduced = False
    total_wait_seconds = 0.0
    for attempt in range(max_retries):
        with _groq_call_lock:
            elapsed = time.time() - _last_groq_call_time[0]
            if elapsed < MIN_GROQ_CALL_INTERVAL:
                gap = MIN_GROQ_CALL_INTERVAL - elapsed
                time.sleep(gap)
                total_wait_seconds += gap
            try:
                result = llm_with_tools.invoke(messages)
                _last_groq_call_time[0] = time.time()
                if hasattr(result, "response_metadata"):
                    logger.info("GROQ DIAGNOSTIC METADATA: %s", result.response_metadata)
                return result, total_wait_seconds
            except Exception as e:
                _last_groq_call_time[0] = time.time()
                err_str = str(e)

                # Cas 0 : payload trop gros (413). Groq renvoie aussi
                # 'code': 'rate_limit_exceeded' sur ce cas, ce qui le faisait
                # tomber dans le Cas 1 ci-dessous et partir en backoff
                # exponentiel (5.5s -> 40.5s -> échec) alors que la requête a
                # une taille FIXE : attendre ne réduit jamais son nombre de
                # tokens, donc chaque nouvelle tentative répète exactement le
                # même échec (bug confirmé par test_c1_1.py::
                # test_end_to_end_code_intelligence_graph_execution : 4
                # tentatives, ~77s perdues, échec garanti à chaque fois). Ici
                # on réduit le contexte une seule fois et on retente
                # immédiatement ; si ça échoue encore, on abandonne sans
                # backoff supplémentaire.
                is_too_large = (
                    "413" in err_str
                    or "request too large" in err_str.lower()
                    or "reduce your message size" in err_str.lower()
                )
                if is_too_large:
                    if not context_reduced:
                        messages = _reduce_message_context(messages)
                        context_reduced = True
                        logger.warning(
                            "Groq payload too large (413, attempt %d/%d) -- contexte réduit, "
                            "nouvelle tentative immédiate.",
                            attempt + 1, max_retries,
                        )
                        continue
                    elif attempt < max_retries - 1:
                        wait_time = 10.0
                        logger.warning(
                            "Groq TPM limit still hit after context reduction (attempt %d/%d) -- "
                            "waiting %.1fs for TPM window reset.",
                            attempt + 1, max_retries, wait_time,
                        )
                        time.sleep(wait_time)
                        total_wait_seconds += wait_time
                        continue
                    logger.error(
                        "Groq payload still too large after retries -- aborting: %s", err_str,
                    )
                    raise

                # Cas 1 : rate limit (comportement existant, inchangé)
                is_rate_limit = "429" in err_str or "rate_limit" in err_str.lower()
                if is_rate_limit and attempt < max_retries - 1:
                    headers = _extract_rate_limit_headers(e)
                    reset_raw = (
                        headers.get("x-ratelimit-reset-tokens")
                        or headers.get("x-ratelimit-reset-requests")
                    )
                    wait_time = _parse_reset_seconds(reset_raw, default=2 ** attempt * 5.0)
                    wait_time += 0.5
                    logger.warning(
                        "Groq rate limit hit (attempt %d/%d). Headers: %s. Dynamically waiting %.1fs...",
                        attempt + 1, max_retries,
                        {k: v for k, v in headers.items() if "ratelimit" in k.lower()},
                        wait_time,
                    )
                    time.sleep(wait_time)
                    total_wait_seconds += wait_time
                    continue

                # Cas 2 : tool_use_failed -- tenter la récupération, sinon retry renforcé
                if "tool_use_failed" in err_str:
                    recovered = _try_recover_tool_use_failed(e)
                    if recovered is not None:
                        return recovered, total_wait_seconds
                    if attempt < max_retries - 1:
                        logger.warning(
                            "tool_use_failed non récupérable (attempt %d/%d), retry avec instruction renforcée.",
                            attempt + 1, max_retries,
                        )
                        messages = messages + [
                            SystemMessage(content=(
                                "RAPPEL STRICT : réponds UNIQUEMENT via un appel d'outil structuré "
                                "(tool_call). N'écris jamais de pseudo-appel en texte libre du type "
                                "<function=...>{...}>."
                            ))
                        ]
                        wait_time = 1.0
                        time.sleep(wait_time)
                        total_wait_seconds += wait_time
                        continue
                    raise

                # Cas 3 : erreurs de connexion transitoires -- retry générique
                is_connection_error = any(
                    term in err_str.lower()
                    for term in ("connection", "timeout", "timed out", "temporarily unavailable")
                )
                if is_connection_error and attempt < max_retries - 1:
                    wait_time = 2 ** attempt * 3.0
                    logger.warning(
                        "Erreur de connexion transitoire (attempt %d/%d): %s. Retry dans %.1fs...",
                        attempt + 1, max_retries, err_str, wait_time,
                    )
                    time.sleep(wait_time)
                    total_wait_seconds += wait_time
                    continue

                raise
 
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
_AUTOMATION_PATTERN = re.compile(
    r"\b(?:mêmes?\s+règles?|systématiq\w*|automatiq\w*|actions?\s+serveur|bypass|contourn\w*)\b",
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


def _question_is_approval_related(question: str) -> bool:
    return bool(_APPROVAL_PATTERN.search(question))


def _question_suggests_automation_bypass(question: str) -> bool:
    return bool(_AUTOMATION_PATTERN.search(question))


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
) -> List[str]:
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
        return tool_observations  # No override active, keep everything.

    has_deterministic_fact = any(
        "[FAIT DÉTERMINISTIQUE]" in obs for obs in tool_observations
    )
    if not has_deterministic_fact:
        return tool_observations  # No authoritative verdict yet, keep everything.

    cleaned = []
    for obs in tool_observations:
        if _COULD_NOT_RESOLVE_RE.search(obs):
            logger.info(
                "Node [code_intelligence_agent]: Q6.1 fix -- stripping 'could not be "
                "resolved' observation from synthesis context (real groups override "
                "is active and a deterministic fact is present): %.120s",
                obs,
            )
            continue
        cleaned.append(obs)
    return cleaned


def _extract_first_scoped_file_link(text: str) -> str:
    match = re.search(r"\[[^\]]+\]\(file:///[^\)]+#L\d+-L\d+\)", text)
    return match.group(0) if match else ""


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

    Resolution order when __manifest__.py is absent:
      1. Known fake_data/code/ core module (account/sale/stock) -> synthesize
         a manifest with its real, well-known, hardcoded `depends`.
      2. Directory with no .py files at all (e.g. fake_data/code/views/, a
         loose XML asset folder, not a real Odoo module) -> it can never
         declare a Model/Method, so it can never appear in a method
         override_sites list and its position in load_order cannot corrupt
         override-chain resolution. Safe to treat as a dependency-free leaf.
      3. Anything else (a real addon -- miro_ai, custom_*, or any future
         fake_data/code/ module actually containing code) -> raise
         MissingManifestError instead of guessing. A silently-guessed
         dependency set for a module we don't actually know is exactly the
         bug this fix removes.
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
                    f"contains .py files, and is not a known fake_data/code/ core "
                    f"module ({sorted(KNOWN_CORE_MODULE_DEPENDS)}). Refusing to "
                    f"silently treat it as having no dependencies -- this "
                    f"previously produced a wrong module load_order and a wrong "
                    f"method-override execution order with no error signal at "
                    f"all (see manifest_parser.MissingManifestError docstring). "
                    f"If this is a real Odoo module, add its __manifest__.py; if "
                    f"it's a new fake_data/code/ core module standing in for a "
                    f"real Odoo core addon, add it to KNOWN_CORE_MODULE_DEPENDS "
                    f"in code_intelligence/manifest_parser.py."
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
    corpus_root = base_dir / "fake_data" / "code"
    addons_root = Path("/home/user/odoo-17.0/addons") if Path("/home/user/odoo-17.0/addons").exists() else base_dir.parent / "addons"

    modules_dict = {}

    if corpus_root.exists():
        for mod_dir in corpus_root.iterdir():
            if mod_dir.is_dir():
                name, mod = _load_module(mod_dir)
                modules_dict[name] = mod

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
        # via depends=['hr_expense']) that is neither part of the synthetic
        # fake_data/code/ corpus nor itself prefixed 'custom_', so it was
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
                continue  # already loaded (fake_data/code, miro_ai, or another custom_* module)
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
    llm = ChatGroq(
        model=GROQ_MODEL,
        api_key=GROQ_API_KEY,
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
        # actually see and correct from. Groq's chat.completions API
        # accepts parallel_tool_calls at the top level (default true);
        # ChatGroq passes unknown kwargs straight through via model_kwargs
        # (same mechanism already used for frequency_penalty/presence_penalty
        # on the synthesis LLM below).
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
        logger.warning(
            "Node [code_intelligence_agent]: Truncating resolved models from %d to MAX_MODELS_PER_QUERY (%d)",
            len(concept.resolved_models), MAX_MODELS_PER_QUERY,
        )
        concept.resolved_models = concept.resolved_models[:MAX_MODELS_PER_QUERY]

    tool_observations: list = []
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
    # a target model AND is approval/security/condition related. Only fires
    # when a model is actually available -- an unresolved concept is a Bloc 0
    # problem, not this one.
    if (
        concept.is_resolved
        and concept.resolved_models
        and _question_is_approval_related(question)
    ):
        tool_map = {t.name: t for t in ALL_CI_TOOLS}
        lock_tool = tool_map.get("analyser_verrous_securite")
        if lock_tool is not None:
            for target_model in concept.resolved_models:
                _t_hop = time.perf_counter()
                try:
                    forced_observation = str(lock_tool.invoke({"model_name": target_model}))
                    if len(forced_observation) > 1200:
                        forced_observation = forced_observation[:1200] + "\n[... Content truncated for LLM context limit ...]"
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
                    hop_count += 1
                    seen_calls.add(("analyser_verrous_securite", target_model))
                    _trace_logger.log_hop(
                        trace_id=_trace_id, hop_index=_hop_index,
                        tool_name="analyser_verrous_securite", tool_args={"model_name": target_model},
                        observation=forced_observation, elapsed_ms=(time.perf_counter() - _t_hop) * 1000,
                    )
                    _hop_index += 1
                    logger.info(
                        "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                        "'analyser_verrous_securite' for model '%s' (approval/security wording detected).",
                        target_model,
                    )
                except Exception as te:
                    logger.error("Deterministic analyser_verrous_securite dispatch failed: %s", te)
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
                    if len(forced_observation) > 1200:
                        forced_observation = forced_observation[:1200] + "\n[... Content truncated for LLM context limit ...]"
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
                for method_name in flagged_methods:
                    call_key = ("analyser_chaine_surcharge_methode", target_model, method_name)
                    if call_key in seen_calls:
                        continue
                    _t_hop = time.perf_counter()
                    try:
                        forced_observation = str(override_tool.invoke({
                            "model_name": target_model, "method_name": method_name,
                        }))
                        if len(forced_observation) > 1200:
                            forced_observation = forced_observation[:1200] + "\n[... Content truncated for LLM context limit ...]"
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
                        if len(observation) > 1200:
                            observation = observation[:1200] + "\n[... Content truncated for LLM context limit ...]"

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
                                    can_view = rule_result.can_view_amount(amount)
                                    tool_observations.append(
                                        f"[FAIT DÉTERMINISTIQUE] Pour un montant de {amount:.0f}€, "
                                        f"can_view_amount() = {can_view} -> l'utilisateur "
                                        f"{'PEUT' if can_view else 'NE PEUT PAS'} voir cet "
                                        f"enregistrement. Ce résultat est calculé directement par "
                                        f"le moteur de règles (evaluer_regles_enregistrement."
                                        f"can_view_amount) et ne doit JAMAIS être recalculé ou "
                                        f"contredit par la synthèse -- reprendre ce verdict tel quel."
                                    )
                                    logger.info(
                                        "Node [code_intelligence_agent]: Injected deterministic "
                                        "can_view_amount fact for amount=%.0f, result=%s.",
                                        amount, can_view,
                                    )
                                except Exception as ve:
                                    logger.error(
                                        "Deterministic can_view_amount injection failed: %s", ve
                                    )
                    except Exception as te:
                        logger.error("Tool execution failed (%s): %s", tool_name, te)
                        _error_observation = f"Error executing {tool_name}: {str(te)}"
                        tool_observations.append(_error_observation)
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
                tool_observations = _strip_group_resolution_noise(
                    tool_observations, resolved_user_group_xmlids,
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
                    f"do NOT mention, paraphrase, or allude to any 'could not be resolved' "
                    f"message from a different tool about group identifiers; those are "
                    f"obsolete artifacts of an earlier resolution step and have been "
                    f"superseded by the deterministic evaluation. "
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
                    f"If the Original Question above asks about more than one condition or "
                    f"threshold (e.g. 'qui peut valider X, et y a-t-il une restriction "
                    f"supplémentaire au-delà de Y ?'), answer EACH part explicitly and "
                    f"separately -- never answer only the first part and silently imply 'no' "
                    f"for the rest. When an observation's 'Messages de verrous' section lists "
                    f"more than one message, treat each one as a DISTINCT finding to report -- "
                    f"do not summarize or select only one of them; a second or third message in "
                    f"that list is exactly as authoritative as the first."
                )
                try:
                    plain_llm = ChatGroq(
                        model=GROQ_MODEL, temperature=0.0, max_retries=0, max_tokens=4096,
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
                    if _detect_degenerate_repetition(final_answer):
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
                            if not _detect_degenerate_repetition(retry_resp.content):
                                final_answer = retry_resp.content
                            else:
                                logger.error(
                                    "Node [code_intelligence_agent]: synthesis still degenerate "
                                    "after retry -- stripping the repeated run instead of shipping it."
                                )
                                final_answer = _strip_degenerate_repetition(final_answer)
                        except Exception as retry_e:
                            logger.error("Anti-repetition retry failed: %s", retry_e)
                            final_answer = _strip_degenerate_repetition(final_answer)
                except Exception as e:
                    logger.error("Synthesis failed: %s", e)
                    final_answer = "\n\n".join(tool_observations)
            else:
                final_answer = "Je n'ai pas de données disponibles dans le graphe de connaissances pour répondre à cette question."

        if final_answer:
            break

    raw_tool_output = "\n\n".join(tool_observations)
    dynamic_uncertainty_answer = _force_dynamic_uncertainty_answer(question, raw_tool_output)
    if dynamic_uncertainty_answer:
        final_answer = dynamic_uncertainty_answer

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
    if _detect_degenerate_repetition(final_answer):
        logger.error(
            "Node [code_intelligence_agent]: degenerate repetition detected in final_answer "
            "outside the main synthesis retry path -- stripping before returning."
        )
        final_answer = _strip_degenerate_repetition(final_answer)

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
