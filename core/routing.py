"""
rag/routing.py

Query classification, routing, and input guardrails.

Keyword-based routing with accent-insensitive matching, inter-branch
conflict priority, sticky session routing, and deterministic input guards.
"""

import logging
import re
import unicodedata
from typing import TypedDict, List, Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from code_intelligence.business_resolver import ResolvedConcept

from langchain_core.messages import BaseMessage

from core.schemas import AssistantResponse, QueryRoute
from code_intelligence.investigation_plan import (
    concept_suggests_code_intelligence_v2,
    generate_investigation_plan,
)

logger = logging.getLogger(__name__)


ERP_TYPES = {"sale", "ticket"}

# Inter-branch conflict policy: code intelligence takes priority for security/governance.
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
    "qui a accès", "qui a acces", "permission d'accès", "permission d acces", "droits d'accès",
    "permission de lecture", "permission d'écriture", "permission de modification", "permission de suppression",
    "quel groupe a accès", "quels groupes ont accès", "qui a le permission",
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
    "peut-il consulter", "peut-elle consulter", "consulter",
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

CONDITIONAL_AMOUNT_TERMS = [
    "quel que soit", "quelle que soit",
]


def _fold_accents(text: str) -> str:
    """Strip diacritics for accent-insensitive keyword matching."""
    return "".join(
        ch for ch in unicodedata.normalize("NFD", text)
        if unicodedata.category(ch) != "Mn"
    )


def _fold_keywords(keywords: list) -> list:
    """Pre-fold a keyword list once at import time, not once per request."""
    return [_fold_accents(kw) for kw in keywords]


# Folded once at import time, reused by every question route() classifies --
# see _fold_accents docstring above for the gap this closes.
ERP_KEYWORDS_FOLDED = _fold_keywords(ERP_KEYWORDS)
CODE_INTEL_KEYWORDS_FOLDED = _fold_keywords(CODE_INTEL_KEYWORDS)
QUANTITATIVE_TERMS_FOLDED = _fold_keywords(QUANTITATIVE_TERMS)
DOC_KEYWORDS_FOLDED = _fold_keywords(DOC_KEYWORDS)
DATA_TERMS_FOLDED = _fold_keywords(DATA_TERMS)
DOC_ANCHORS_FOLDED = _fold_keywords(DOC_ANCHORS)
THRESHOLD_QUERY_TERMS_FOLDED = _fold_keywords(THRESHOLD_QUERY_TERMS)
CONDITIONAL_AMOUNT_TERMS_FOLDED = _fold_keywords(CONDITIONAL_AMOUNT_TERMS)


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
    user_groups: List[int]  # Real Odoo group ids of the requester
    resolved_concept: Optional[dict]  # Deterministic business_resolver output
    last_route: Optional[str]  # Previous turn's route for sticky routing
    last_resolved_concept: Optional[dict]  # Previous turn's resolved concept
    resolved_concept_reused: bool  # True when reusing the previous turn's concept
    evidence_status: Optional[str]  # Sourcing evidence status: RESOLU/NON_RESOLU/CONFLIT
    investigation_plan: Optional[dict]  # A priori InvestigationPlan (Bloc P1), display-shaped



# ── Nodes ─────────────────────────────────────────────────────────────────────

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
    """Detect queries attempting bulk metadata or rule extraction across all models/modules."""
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
    """Detect prompt injection and system prompt reveal attempts."""
    import re
    q = question.lower().strip()
    if not q:
        return False
    return any(re.search(pat, q) for pat in _PROMPT_INJECTION_PATTERNS)


_VALID_ROUTES = {r.value for r in QueryRoute}



def _sticky_route_or_default(state: RAGState, default: str) -> str:
    """
    Sticky session routing: when the current question carries no keyword signal,
    reuse the previous turn's branch instead of defaulting to DOCUMENTAIRE.
    """
    last_route = state.get("last_route")
    if last_route in _VALID_ROUTES:
        logger.info(
            "Node [route]: No keyword signal on current question -- "
            "sticky-routing to previous turn's branch (%s) instead of %s default",
            last_route, default,
        )
        return last_route
    return default


def _sticky_concept_or_resolve(state: RAGState, resolved_concept_dict: dict) -> dict:
    """
    Sticky concept reuse: when the current question fails to resolve to a business concept,
    reuse the previous turn's resolved concept for the session if available.
    """
    if resolved_concept_dict.get("is_resolved"):
        return resolved_concept_dict
    prev = state.get("last_resolved_concept")
    if isinstance(prev, dict) and prev.get("is_resolved") is True:
        logger.info("Node [route]: reusing previous resolved_concept.")
        return prev
    return resolved_concept_dict


def route(state: RAGState) -> dict:
    """Classify the query using keyword patterns and conflict priorities."""
    import time
    start_time = time.time()
    chunks = state.get("retrieved_chunks", [])
    question = state.get("question", "").lower()
    question_folded = _fold_accents(question)
    logger.info("Node [route]: Classifying query type from %d chunks", len(chunks))

    from code_intelligence.business_resolver import resolve_business_term
    from code_intelligence.ci_graph_loader import get_code_intelligence_graph
    G = get_code_intelligence_graph()
    resolved_concept = resolve_business_term(
        state.get("question", ""), G, llm=None
    )

    # Hybrid check: doc keyword/anchor + quantitative ERP term
    is_hybrid = (
        any(kw in question_folded for kw in DOC_KEYWORDS_FOLDED) or any(a in question_folded for a in DOC_ANCHORS_FOLDED)
    ) and any(term in question_folded for term in QUANTITATIVE_TERMS_FOLDED)

    # Conflict resolution priority:
    # 1. Explicit doc anchors override everything (user explicitly asks for wiki/policy doc)
    # 2. Quantitative data queries ("combien", "montant total des...", "nombre de...") -> DONNEES_ERP,
    #    UNLESS it's explicitly asking about a governance threshold ("dépasse-t-il le seuil", "quel est le plafond")
    # 3. CODE_INTELLIGENCE > DONNEES_ERP > HYBRIDE > DOCUMENTAIRE
    has_doc_anchor = any(anchor in question_folded for anchor in DOC_ANCHORS_FOLDED)
    has_code_intel = any(kw in question_folded for kw in CODE_INTEL_KEYWORDS_FOLDED)
    has_erp = any(kw in question_folded for kw in ERP_KEYWORDS_FOLDED)
    has_quantitative = any(term in question_folded for term in QUANTITATIVE_TERMS_FOLDED)
    is_threshold_query = any(t in question_folded for t in THRESHOLD_QUERY_TERMS_FOLDED)
    is_conditional_amount_query = any(t in question_folded for t in CONDITIONAL_AMOUNT_TERMS_FOLDED)

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
    elif has_quantitative and not is_threshold_query and not is_conditional_amount_query:
        # Quantitative record count/sum lookup -> DONNEES_ERP wins over code_intel
        logger.info("Node [route]: Quantitative data query → DONNEES_ERP branch")
        route_decision = QueryRoute.DONNEES_ERP.value
    elif has_code_intel:
        # Code intelligence wins over doc/erp for governance questions
        logger.info("Node [route]: Query matched Code Intelligence keywords → CODE_INTELLIGENCE branch")
        route_decision = QueryRoute.CODE_INTELLIGENCE.value
    elif any(kw in question_folded for kw in DOC_KEYWORDS_FOLDED):
        logger.info("Node [route]: Query matched explicit doc keywords → DOCUMENTAIRE branch")
        route_decision = QueryRoute.DOCUMENTAIRE.value
    elif has_erp:
        logger.info("Node [route]: Query matched explicit ERP keywords → DONNEES_ERP branch")
        route_decision = QueryRoute.DONNEES_ERP.value
    elif not chunks:
        if concept_suggests_code_intelligence_v2(state.get("question", ""), resolved_concept, G):
            logger.info(
                "Node [route]: No chunks, no keyword signal, but resolved_concept "
                "+ classified Code Intelligence intent → CODE_INTELLIGENCE branch (Bloc P1 gate)"
            )
            route_decision = QueryRoute.CODE_INTELLIGENCE.value
        else:
            route_decision = _sticky_route_or_default(state, QueryRoute.DOCUMENTAIRE.value)
            logger.info("Node [route]: No chunks, no keyword signal → %s", route_decision)
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

        if erp_ratio >= 0.6 and any(term in question_folded for term in DATA_TERMS_FOLDED):
            logger.info("Node [route]: High ERP ratio + data terms → DONNEES_ERP branch")
            route_decision = QueryRoute.DONNEES_ERP.value
        elif concept_suggests_code_intelligence_v2(state.get("question", ""), resolved_concept, G):
            logger.info(
                "Node [route]: No strong signal, but resolved_concept + "
                "classified Code Intelligence intent → CODE_INTELLIGENCE branch (Bloc P1 gate)"
            )
            route_decision = QueryRoute.CODE_INTELLIGENCE.value
        else:
            route_decision = _sticky_route_or_default(state, QueryRoute.DOCUMENTAIRE.value)
            logger.info("Node [route]: No strong signal (erp_ratio fallback) → %s", route_decision)

    timing = state.get("timing", {}).copy()
    timing["routing_time"] = time.time() - start_time

    from dataclasses import asdict as _asdict
    resolved_concept_dict = _asdict(resolved_concept)

    # Sticky reuse of previous turn's concept if current resolution failed
    resolved_concept_dict = _sticky_concept_or_resolve(state, resolved_concept_dict)

    resolved_concept_reused = resolved_concept_dict is state.get("last_resolved_concept")

    investigation_plan = generate_investigation_plan(
        question=state.get("question", ""),
        resolved_concept=resolved_concept,
        G=G,
        user_groups=state.get("user_groups"),
    )

    return {
        "route": route_decision,
        "timing": timing,
        "resolved_concept": resolved_concept_dict,
        "resolved_concept_reused": resolved_concept_reused,
        "investigation_plan": investigation_plan.to_display_dict(),
    }


def route_decision(state: RAGState) -> str:
    """Return the routing key for conditional edges."""
    return state.get("route", QueryRoute.DOCUMENTAIRE.value)

