"""
core/routing.py

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
    INTENT_TO_ROUTE,
    QuestionIntent,
    generate_investigation_plan,
    has_documentary_anchor,
    resolve_question_intent,
    validate_plan_against_route,
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

# Pure arithmetic expression (e.g. "8+9", "12 * 3 =", "8+9?") -- no keyword
# signal, no business concept, and was previously falling through to
# sticky-routing (_sticky_route_or_default), inheriting the last turn's
# branch instead of being recognized as out-of-scope. See
# todo/contexte.txt section 373.
_ARITHMETIC_ONLY_RE = re.compile(
    r"^\s*\d+(?:[.,]\d+)?\s*[+\-*/]\s*\d+(?:[.,]\d+)?"
    r"(?:\s*[+\-*/]\s*\d+(?:[.,]\d+)?)*"
    r"(?:\s*=\s*\d*(?:[.,]\d+)?)?\s*\??\s*$"
)

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
    sources_fallback_eligible: Optional[bool]  # True only when generate()'s raw (non-structured) LLM fallback was used
    ci_evidence_sufficiency: Optional[dict]  # Post-analysis CI answer sufficiency verdict (Bloc P1 Tranche 2, core/evidence_sufficiency.py) -- drives the CI-first/RAG-fallback conditional edge in core/graph.py



# ── Nodes ─────────────────────────────────────────────────────────────────────

def _is_out_of_scope(question: str) -> bool:
    """Reject obvious non-work questions before the LLM can improvise."""
    normalized_question = question.lower().strip()
    if not normalized_question:
        return False

    if _ARITHMETIC_ONLY_RE.match(normalized_question):
        return True

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
    r"(?:liste|dump|export|afficher?|donne)\w*\s+(?:de\s+)?tous\s+les\s+utilisateurs",
    r"tous\s+les\s+utilisateurs\s+et\s+(?:leurs\s+)?mots\s+de\s+passe",
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
    """
    Classify the query via intent-based routing (Bloc P1 Tranche 2,
    todo/contexte.txt section 394+).

    Replaces the previous two independently-maintained classifiers --
    route()'s own CODE_INTEL_KEYWORDS/ERP_KEYWORDS/DOC_KEYWORDS cascade plus
    the chunk-based ERP-ratio fallback, and generate_investigation_plan()'s
    separate classify_question_intent() call -- with a SINGLE
    resolve_question_intent() call whose result feeds both the route
    decision (via INTENT_TO_ROUTE) and the investigation plan (via the
    `intent` parameter added to generate_investigation_plan()). This
    eliminates the plan/route divergence at its root instead of only
    detecting it after the fact: validate_plan_against_route() below is
    kept as a defensive net, but on this path the two are now derived from
    the same classification, so it has no real conflict left to catch.
    """
    import time
    start_time = time.time()
    question_raw = state.get("question", "")
    question_folded = _fold_accents(question_raw.lower())
    logger.info("Node [route]: Classifying query type via intent resolution")

    from code_intelligence.business_resolver import resolve_business_term
    from code_intelligence.ci_graph_loader import get_code_intelligence_graph
    G = get_code_intelligence_graph()
    resolved_concept = resolve_business_term(question_raw, G, llm=None)

    intent_resolution = resolve_question_intent(question_raw, resolved_concept, G)
    intent = intent_resolution.intent
    logger.info("Node [route]: intent=%s source=%s", intent.value, intent_resolution.source)

    # Fix (Cluster B, test_h1c_sticky_routing.py::test_keyword_match_wins_over_contrary_last_route):
    # this used to be `any(anchor in question_folded for anchor in
    # DOC_ANCHORS_FOLDED)` -- a SEPARATE, narrower literal-substring list
    # maintained only in this file, which had drifted out of sync with the
    # actual anchor detection used to classify DOCUMENTARY_POLICY in the
    # first place (code_intelligence/investigation_plan.py's
    # _DOC_ANCHOR_PATTERNS, e.g. it recognizes "procédure"/"documentation"/
    # "guide utilisateur", none of which DOC_ANCHORS listed). A question
    # like "Quelle est la procédure de validation ?" was correctly classified
    # DOCUMENTARY_POLICY via an explicit anchor, but this local check missed
    # it, wrongly treating the question as "no signal" and letting
    # sticky-routing override an explicitly-anchored classification. Now
    # reuses has_documentary_anchor() -- the SAME function that produced the
    # DOCUMENTARY_POLICY classification -- as the single source of truth,
    # instead of two independently-maintained anchor definitions. DOC_ANCHORS/
    # DOC_ANCHORS_FOLDED above are kept only for backward-compat imports
    # (tests, re-exports) and are no longer used to compute this flag.
    has_doc_anchor = has_documentary_anchor(question_folded)
    derived_route = INTENT_TO_ROUTE.get(intent, QueryRoute.DOCUMENTAIRE.value)

    if intent == QuestionIntent.DOCUMENTARY_POLICY and not has_doc_anchor:
        # Sticky-routing redefinition (Tranche 2): DOCUMENTARY_POLICY without
        # an explicit anchor is the classifier's own "nothing more specific
        # matched" bucket (classify_question_intent()'s step 9 default, and
        # the LLM prompt's equivalent catch-all) -- the same case sticky
        # routing previously covered as "no keyword signal". An EXPLICIT
        # anchor ("selon le wiki...") is a real signal, not an absence of
        # one, so it is excluded here and always routes to documentaire
        # directly below, unaffected by session history -- preserves the
        # pre-existing DOC-08 guarantee that an explicit wiki/policy
        # reference always wins.
        route_decision = _sticky_route_or_default(state, QueryRoute.DOCUMENTAIRE.value)
        logger.info(
            "Node [route]: DOCUMENTARY_POLICY, no explicit anchor -> sticky/default (%s)",
            route_decision,
        )
    else:
        route_decision = derived_route

    # HYBRIDE layer: a lightweight pass applied ONLY on top of a documentaire/
    # donnees_erp derived route, never on code_intelligence -- priority
    # unchanged from before this rewrite (CODE_INTELLIGENCE always wins
    # outright). Reuses the pre-existing doc-anchor/keyword + quantitative-
    # term heuristic, itself untouched.
    if route_decision in (QueryRoute.DOCUMENTAIRE.value, QueryRoute.DONNEES_ERP.value):
        is_hybrid = (
            any(kw in question_folded for kw in DOC_KEYWORDS_FOLDED) or has_doc_anchor
        ) and any(term in question_folded for term in QUANTITATIVE_TERMS_FOLDED)
        if is_hybrid:
            logger.info("Node [route]: doc-anchor/keyword + quantitative term -> HYBRIDE layer")
            route_decision = QueryRoute.HYBRIDE.value

    timing = state.get("timing", {}).copy()
    timing["routing_time"] = time.time() - start_time

    from dataclasses import asdict as _asdict
    resolved_concept_dict = _asdict(resolved_concept)

    # Sticky reuse of previous turn's concept if current resolution failed
    resolved_concept_dict = _sticky_concept_or_resolve(state, resolved_concept_dict)

    resolved_concept_reused = resolved_concept_dict is state.get("last_resolved_concept")

    # Tranche 2: reuse the SAME `intent` already resolved above -- skips
    # generate_investigation_plan()'s own classify_question_intent() call
    # entirely via its new `intent` parameter (see investigation_plan.py),
    # instead of relying on validate_plan_against_route() to catch a
    # divergence after the fact.
    investigation_plan = generate_investigation_plan(
        question=question_raw,
        resolved_concept=resolved_concept,
        G=G,
        user_groups=state.get("user_groups"),
        intent=intent,
    )
    investigation_plan = validate_plan_against_route(investigation_plan, route_decision)

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

