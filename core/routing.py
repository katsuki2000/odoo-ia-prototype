"""
rag/routing.py

Query classification, routing, and input guardrails.

Keyword-based routing with accent-insensitive matching, inter-branch
conflict priority (Bloc 6), sticky session routing (H1c), and
deterministic input guards (out-of-scope, massive extraction, prompt injection).
"""

import logging
import re
import unicodedata
from typing import TypedDict, List, Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from code_intelligence.business_resolver import ResolvedConcept

from langchain_core.messages import BaseMessage

from core.schemas import AssistantResponse, QueryRoute

logger = logging.getLogger(__name__)


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
    # 2026-08-21 (todo/contexte.txt section 93, bug C) : "consulter" est un
    # synonyme courant de "voir"/"accéder" en formulation informelle
    # (cf. bloc9-08c-bis) mais n'était couvert par aucune des 7 listes de
    # mots-clés -- repli sans-signal (DOCUMENTAIRE) au lieu de
    # CODE_INTELLIGENCE. Ajout pur, zéro risque de régression.
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

# Bug A / pattern H4 (2026-08-21, todo/contexte.txt sections 93/106/107):
# consulted ONLY inside the two no-signal fallback branches of route() below
# (never as a standalone branch, never with higher precedence than any of
# the 7 keyword lists above) -- see _concept_suggests_code_intelligence's
# own docstring for the full rationale and the DOC-08 counter-example that
# makes "resolved_concept.is_resolved alone" unsafe as a redirect signal.
# Deliberately narrow: covers only the vocabulary actually present in the
# 5 confirmed H4 questions (01c, 03a, 03c, 04c, 05c), verified absent from
# all 30 questions of tests/benchmark_questions.json where it must NOT
# fire (in particular DOC-08, the one question that reaches this same
# fallback with a successful resolution but where DOCUMENTAIRE is the
# correct branch).
GOVERNANCE_SIGNAL_TERMS = [
    "valid",  # substring: covers valider/validée/validation (01c, 03a, 03c, 04c)
    "règle", "s'applique",  # 05c ("la règle de séparation des rôles ... s'applique-t-elle")
    "échappe",  # 01c ("échappe-t-il au contrôle")
    "automatique",  # 03c ("automatiquement validée")
    "contrôle",  # 01c ("contrôle de validation")
]

def _fold_accents(text: str) -> str:
    """Strip diacritics for accent-insensitive keyword matching (NFD
    decomposition + drop Unicode combining marks, category 'Mn'). Root-cause
    fix for a routing gap found live (2026-08-19, todo/contexte.txt): every
    keyword list above is matched with a plain Python `in` on `question`,
    with zero accent normalization -- an accented list entry (e.g. "cette
    année") silently never matches an unaccented user question ("cette
    annee"), regardless of which of the 7 lists it lives in. Applied to
    both sides of every match in route() below (the raw lists above keep
    their accents for readability -- only the comparison is folded), so any
    keyword added later to any of the 7 lists is covered automatically --
    no per-entry duplicate upkeep (unlike BUSINESS_ALIASES in
    business_resolver.py, whose static aliases are hand-reviewed one at a
    time and can afford to list both forms explicitly).
    """
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
GOVERNANCE_SIGNAL_TERMS_FOLDED = _fold_keywords(GOVERNANCE_SIGNAL_TERMS)


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
    uid: Optional[int]  # Odoo user uid for RBAC passthrough
    user_groups: List[int]  # Real Odoo group ids of the requester (signed JWT, never LLM-guessed)
    resolved_concept: Optional[dict]  # H1 prototype (2026-08-19): deterministic business_resolver output computed in route(), before branch dispatch -- see route()'s own docstring/comment for scope
    last_route: Optional[str]  # H1c (2026-08-19, todo/plan.md): previous turn's QueryRoute value for this session, supplied by the caller (query_graph(), sourced from session_store) -- None on the first turn of a session or when the caller passes none. Consumed only by route()'s no-signal fallback branches for sticky-routing (see _sticky_route_or_default docstring); every keyword-matched branch is unaffected.
    last_resolved_concept: Optional[dict]  # H1b-ii (2026-08-20, todo/contexte.txt section 64/70): previous turn's resolved_concept dict for this session (AssistantResponse.resolved_concept, round-tripped through session_store), supplied by the caller (query_graph()) -- None on a session's first turn or when the caller passes none. Consumed only by _sticky_concept_or_resolve, mirroring last_route/_sticky_route_or_default exactly; never mutated inside the graph.
    resolved_concept_reused: bool  # H3 (2026-08-20, todo/contexte.txt): True when route()'s resolved_concept this turn is literally the previous turn's dict, reused as-is by _sticky_concept_or_resolve because the CURRENT question's own text resolved to nothing -- False otherwise (fresh resolution succeeded this turn, or nothing resolved anywhere). Computed by object identity in route() (`is`), never by inspecting resolved_concept's own fields -- deliberately kept OUT of the resolved_concept dict itself, since _rehydrate_sticky_concept (rag/ci_helpers.py) reconstructs a ResolvedConcept dataclass via **dict and silently degrades to unresolved on any unexpected key (see test_sticky_dict_malformed_fields_degrades_without_raising) -- adding a marker key there would silently break H1b-ii's own rehydration. Consumed only by rag/evidence_check.py's check_evidence(), read-only, never mutated after route().
    evidence_status: Optional[str]  # H3 (2026-08-20, todo/contexte.txt), Phase 1 -- observational only: RESOLU/NON_RESOLU/CONFLIT computed by rag/evidence_check.py's check_evidence(), set only by code_intelligence_agent (None on every other branch, which has no resolved_concept to reconcile). Does not affect tool dispatch, system_prompt content, or gating in this phase -- surfaced purely for measurement (propagated to AssistantResponse.evidence_status by format_output(), same central-assignment pattern as route/resolved_concept). What each status should DO, if anything, is deferred to a follow-up step once measured against the adversarial benchmark.



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


_VALID_ROUTES = {r.value for r in QueryRoute}



def _sticky_route_or_default(state: RAGState, default: str) -> str:
    """
    H1c (2026-08-19, todo/plan.md preconditions section): route() decides
    purely from the current question's own text (keyword lists + the
    ERP-ratio-of-retrieved-chunks fallback) -- chat_history is passed into
    RAGState but was never consulted for the routing decision itself (see
    plan.md's own confirmed finding via tests/manual_check_session_
    persistence.py: chat_history_len=2 on turn 2, ERP ratio still computed
    from the isolated current-turn text, still defaulting to DOCUMENTAIRE
    on an elliptical follow-up like "Et pour cette année ?"). Design
    decided with the maître de stage: sticky-routing, not context-informed
    reclassification -- when the CURRENT question carries no keyword
    signal strong enough to pick a branch on its own, reuse the PREVIOUS
    turn's branch instead of unconditionally guessing DOCUMENTAIRE.

    Deliberately scoped to only the two callers of this helper in route()
    below -- both are the pre-existing "nothing matched" fallbacks (no
    chunks at all; chunks retrieved but neither a high ERP ratio nor a
    DATA_TERMS hit). Every branch driven by an actual keyword/anchor match
    (doc anchor, hybrid, quantitative, code_intel keyword, doc keyword,
    erp keyword) is completely untouched -- this can only ever change a
    decision that was already a guess with zero real signal, so no
    currently-locked routing test or benchmark question that matches any
    keyword list can regress, verifiable by inspection the same way H1's
    own no-op step was (contexte.txt section 62).

    last_route is read from state, not computed here -- it is supplied by
    the caller (query_graph(), sourced from session_store's per-session
    last_route) and is None on a session's first turn or whenever the
    caller has nothing to offer, in which case this simply returns
    `default` unchanged (identical behaviour to before this fix, so a
    first-turn question -- the overwhelming majority of every existing
    test and benchmark run, none of which pass last_route -- is completely
    unaffected). Only a recognized QueryRoute value is honored, so a
    corrupted/foreign string stored anywhere upstream can never be echoed
    back as a route decision.
    """
    last_route = state.get("last_route")
    if last_route in _VALID_ROUTES:
        logger.info(
            "Node [route]: No keyword signal on current question -- "
            "sticky-routing to previous turn's branch (%s) instead of the "
            "hardcoded %s default", last_route, default,
        )
        return last_route
    return default


def _sticky_concept_or_resolve(state: RAGState, resolved_concept_dict: dict) -> dict:
    """
    H1b-ii (2026-08-20, todo/contexte.txt section 64/70): mirrors
    _sticky_route_or_default exactly, one level down -- when the CURRENT
    question's own deterministic resolution (already computed above in
    route(), with llm=None) failed (is_resolved=False), reuse the
    PREVIOUS turn's resolved_concept for this session instead of leaving
    is_resolved=False. Never the reverse: a current-turn resolution that
    already succeeded always wins untouched -- this can only ever replace
    a result that was already a total miss, so no currently-locked
    resolver test can regress (same argument already made for
    _sticky_route_or_default).

    Deliberately operates strictly on the dict form (post-_asdict), never
    on the ResolvedConcept dataclass: resolved_concept_dict is the exact
    JSON/session-store-safe shape route() itself stores on
    state["resolved_concept"] (see the comment above _asdict's call site
    for why -- avoids leaking the dataclass type into RAGState's TypedDict
    contract), and state["last_resolved_concept"] arrives in that same
    dict shape, round-tripped through AssistantResponse.resolved_concept ->
    session_store -> here. Calling dataclasses.asdict() on a dict instead
    of a dataclass instance raises TypeError -- this function's whole
    point is to never let that mismatch happen by keeping both sides of
    the comparison as plain dicts. (A caller needing a real ResolvedConcept
    object back, e.g. ci_agent_node.py's own attribute-based consumption of
    concept.is_resolved/concept.resolved_models/etc., must reconstruct one
    explicitly via ResolvedConcept(**the_dict) at its own call site -- this
    function never does that reconstruction itself.)

    Only reused when the previous concept is itself marked resolved
    (`is True`, not merely truthy, per rules.md Regle 4/5 discipline) --
    a stored is_resolved=False, or a corrupted/foreign dict missing the
    key entirely, must never be echoed back as if it were a real
    resolution. state.get("last_resolved_concept") is None on a session's
    first turn or whenever the caller has nothing to offer, in which case
    this simply returns resolved_concept_dict unchanged (identical
    behaviour to before this fix).
    """
    if resolved_concept_dict.get("is_resolved"):
        return resolved_concept_dict
    prev = state.get("last_resolved_concept")
    if isinstance(prev, dict) and prev.get("is_resolved") is True:
        logger.info("Node [route]: reusing previous resolved_concept.")
        return prev
    return resolved_concept_dict


def _concept_suggests_code_intelligence(question_folded: str, resolved_concept) -> bool:
    """
    Bug A / pattern H4 fix (2026-08-21, todo/contexte.txt sections 93/106/107,
    mandat explicite utilisateur "Feu vert pour implémenter la proposition").

    Consulted ONLY by the two no-signal fallback branches of route() below
    (no chunks at all; chunks retrieved but neither a high ERP ratio nor a
    DATA_TERMS hit) -- every branch driven by an actual keyword/anchor match
    is completely untouched, so this can only ever change a decision that
    was already a guess with zero real signal (same non-regression argument
    already made for _sticky_route_or_default, whose fallback default this
    function preempts, not replaces).

    Root cause this closes (H4, confirmed 5x -- 01c, 03a, 03c, 04c, 05c,
    sections 77/80/82/86/93): resolved_concept is the single most
    deterministic component in this pipeline (static alias / exact
    technical mention tiers, zero LLM cost), computed earlier in route(),
    but the no-signal fallbacks never consulted it and always guessed
    DOCUMENTAIRE (or stuck to whatever the previous turn's route was).

    NOT a bare "is_resolved implies CODE_INTELLIGENCE" check, deliberately
    -- that was found to be UNSAFE while re-verifying this diagnosis against
    the full 30-question benchmark (tests/benchmark_questions.json) before
    writing this function: DOC-08 ("Quel est le délai de traitement pour
    une demande de mise à disposition ?") reaches this exact same fallback
    (no keyword list matches it either) and resolves via the same
    zero-ambiguity static-alias tier ("mise à disposition" ->
    custom.asset.loan, is_resolved=True, confidence=1.0) as 01c's "avoir" --
    yet DOCUMENTAIRE is the correct branch for DOC-08 (it asks about a
    documented SLA, not a governance/behavior question). A prior session
    (todo/contexte.txt section 77) had assumed DOC-08 was safe because it
    would be "intercepted earlier by DOC_KEYWORDS" -- re-checked keyword by
    keyword here and that assumption was WRONG; DOC-08 matches none of the
    7 existing keyword lists, so it truly does fall through to this same
    fallback and would have regressed under a bare is_resolved check.

    Fix: require BOTH signals at once (same AND-gate shape already used by
    is_hybrid above in this file), not resolved_concept alone --
    resolved_concept.is_resolved AND at least one GOVERNANCE_SIGNAL_TERMS
    hit. The 5 confirmed H4 questions all ask about a rule/validation/
    behavior of the resolved business object ("échappe au contrôle",
    "valider"/"automatiquement validée", "la règle ... s'applique-t-elle"),
    never a plain informational fact like DOC-08's delay -- verified term
    by term that GOVERNANCE_SIGNAL_TERMS covers all 5 H4 questions and is
    absent from all 30 benchmark questions where it must not fire (DOC-08
    in particular, the only other benchmark question reaching this
    fallback with a successful resolution).

    resolved_concept is the raw dataclass computed earlier in route()
    (before the sticky H1b-ii reuse / _asdict conversion below), not the
    dict form -- this only ever looks at the CURRENT question's own fresh
    resolution, deliberately never a reused previous-turn concept (sticky
    concept reuse is a separate, already-reviewed mechanism -- see
    _sticky_concept_or_resolve -- not something this new gate should also
    second-guess).
    """
    if resolved_concept is None or not getattr(resolved_concept, "is_resolved", False):
        return False
    return any(term in question_folded for term in GOVERNANCE_SIGNAL_TERMS_FOLDED)


def route(state: RAGState) -> dict:
    """Classify the query using the Bloc 6 inter-branch conflict policy."""
    import time
    start_time = time.time()
    chunks = state.get("retrieved_chunks", [])
    question = state.get("question", "").lower()
    # 2026-08-19 fix (todo/contexte.txt): accent-insensitive keyword matching
    # -- see _fold_accents docstring above. `question` above is kept as-is
    # (still used for logging / non-keyword logic elsewhere); only the
    # keyword membership checks below switch to the folded form.
    question_folded = _fold_accents(question)
    logger.info("Node [route]: Classifying query type from %d chunks", len(chunks))

    # H1 prototype (2026-08-19, contexte.txt section 60/61 finding F2):
    # business_resolver.py is the single most deterministic component in
    # this pipeline (static alias / exact technical mention tiers are
    # zero-LLM-cost, near-zero-latency -- see business_resolver.py's own
    # module docstring), but until now it was only ever invoked *inside*
    # code_intelligence_agent (this file, ~L3720) -- i.e. strictly AFTER
    # route() had already picked a branch. F2's own text is precise about
    # what this means: the resolver simply never runs at all for a
    # question that names a business term without also matching one of
    # the CODE_INTEL_KEYWORDS/ERP_KEYWORDS/DOC_KEYWORDS lists.
    #
    # Deliberately observational-only in this first step: resolve here
    # with llm=None (skips the bounded-LLM-arbitration tier entirely, so
    # this adds zero LLM calls/latency to every single question just to
    # route it) and store the result on state -- but do NOT use it to
    # change route_decision yet. A hand-traced check against this
    # project's own benchmark_questions.json caught a real regression risk
    # before it shipped: DOC-08 ("Quel est le délai de traitement pour une
    # demande de mise à disposition ?") deterministically resolves via the
    # "mise à disposition" static alias to custom.asset.loan, yet the
    # right branch for that question is DOCUMENTAIRE (it asks about an SLA
    # documented in the wiki, not about code/governance) -- proof that
    # "business_resolver identified a model" does not imply "route to
    # CODE_INTELLIGENCE", which is a distinct, unproven claim (the same
    # gap H4 in section 60/61 already flags as its least-evidenced
    # hypothesis). Every existing branch's precedence (doc anchor > hybrid
    # > quantitative > code_intel keyword > doc keyword > erp keyword >
    # no-chunks/erp-ratio default) is therefore completely unchanged here
    # -- this step is a strict no-op on route_decision, verifiable by
    # inspection, so no currently-locked routing test or benchmark
    # question can regress. Consuming this signal to actually change a
    # routing decision is deferred to a follow-up step, once a real
    # decision rule (not a guess) has been designed and measured -- see
    # contexte.txt for the phasing this belongs to.
    from code_intelligence.business_resolver import resolve_business_term
    from code_intelligence.ci_graph_loader import get_code_intelligence_graph
    resolved_concept = resolve_business_term(
        state.get("question", ""), get_code_intelligence_graph(), llm=None
    )

    # Hybrid check: doc keyword/anchor + quantitative ERP term (not just generic nouns like 'facture').
    # Must include DOC_ANCHORS, not only DOC_KEYWORDS: anchors like "où est documenté" or
    # "dans le wiki" are not in DOC_KEYWORDS, so a query combining one of them with a
    # quantitative term (e.g. "Où est documenté le nombre de tickets en cours ?") was
    # silently falling through to DOCUMENTAIRE instead of HYBRIDE. Found in review, locked
    # by test_hybrid_detects_doc_anchor_not_only_doc_keyword.
    is_hybrid = (
        any(kw in question_folded for kw in DOC_KEYWORDS_FOLDED) or any(a in question_folded for a in DOC_ANCHORS_FOLDED)
    ) and any(term in question_folded for term in QUANTITATIVE_TERMS_FOLDED)

    # J18-J19: Conflict resolution priority:
    # 1. Explicit doc anchors override everything (user explicitly asks for wiki/policy doc)
    # 2. Quantitative data queries ("combien", "montant total des...", "nombre de...") -> DONNEES_ERP,
    #    UNLESS it's explicitly asking about a governance threshold ("dépasse-t-il le seuil", "quel est le plafond")
    # 3. CODE_INTELLIGENCE > DONNEES_ERP > HYBRIDE > DOCUMENTAIRE
    has_doc_anchor = any(anchor in question_folded for anchor in DOC_ANCHORS_FOLDED)
    has_code_intel = any(kw in question_folded for kw in CODE_INTEL_KEYWORDS_FOLDED)
    has_erp = any(kw in question_folded for kw in ERP_KEYWORDS_FOLDED)
    has_quantitative = any(term in question_folded for term in QUANTITATIVE_TERMS_FOLDED)
    is_threshold_query = any(t in question_folded for t in THRESHOLD_QUERY_TERMS_FOLDED)

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
    elif any(kw in question_folded for kw in DOC_KEYWORDS_FOLDED):
        logger.info("Node [route]: Query matched explicit doc keywords → DOCUMENTAIRE branch")
        route_decision = QueryRoute.DOCUMENTAIRE.value
    elif has_erp:
        logger.info("Node [route]: Query matched explicit ERP keywords → DONNEES_ERP branch")
        route_decision = QueryRoute.DONNEES_ERP.value
    elif not chunks:
        if _concept_suggests_code_intelligence(question_folded, resolved_concept):
            logger.info(
                "Node [route]: No chunks, no keyword signal, but resolved_concept "
                "+ governance-signal term → CODE_INTELLIGENCE branch (Bug A / H4 fix)"
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
        elif _concept_suggests_code_intelligence(question_folded, resolved_concept):
            logger.info(
                "Node [route]: No strong signal, but resolved_concept + "
                "governance-signal term → CODE_INTELLIGENCE branch (Bug A / H4 fix)"
            )
            route_decision = QueryRoute.CODE_INTELLIGENCE.value
        else:
            route_decision = _sticky_route_or_default(state, QueryRoute.DOCUMENTAIRE.value)
            logger.info("Node [route]: No strong signal (erp_ratio fallback) → %s", route_decision)

    timing = state.get("timing", {}).copy()
    timing["routing_time"] = time.time() - start_time

    # H1 prototype: expose the deterministic resolver result on state as a
    # plain dict (JSON/graph-checkpoint friendly, avoids leaking the
    # dataclass type into RAGState's TypedDict contract) regardless of
    # which branch was picked -- see the comment block above for scope.
    from dataclasses import asdict as _asdict
    resolved_concept_dict = _asdict(resolved_concept)

    # H1b-ii (2026-08-20, todo/contexte.txt section 64/70): sticky reuse of
    # the previous turn's resolved_concept when the current question's own
    # resolution (above) failed -- see _sticky_concept_or_resolve's
    # docstring for the full rationale and why this MUST run after
    # _asdict() (dict-only, never the dataclass) rather than before it.
    resolved_concept_dict = _sticky_concept_or_resolve(state, resolved_concept_dict)

    # H3 (2026-08-20, todo/contexte.txt): was the dict above just reused,
    # unchanged, from the PREVIOUS turn (i.e. this turn's own text -- both
    # code_intelligence_agent's real-LLM attempt is downstream and unknown
    # here, but route()'s own no-LLM attempt specifically -- resolved to
    # nothing)? Object identity, not a field comparison: _sticky_concept_or_
    # resolve returns `prev` (== state["last_resolved_concept"]) literally
    # unchanged when it reuses, and a freshly-resolved dict otherwise -- so
    # `is` is exact and free, no extra bookkeeping needed. See RAGState's
    # own field comment above for why this is a separate state key rather
    # than a marker inside resolved_concept_dict itself.
    resolved_concept_reused = resolved_concept_dict is state.get("last_resolved_concept")

    return {
        "route": route_decision,
        "timing": timing,
        "resolved_concept": resolved_concept_dict,
        "resolved_concept_reused": resolved_concept_reused,
    }


def route_decision(state: RAGState) -> str:
    """Return the routing key for conditional edges."""
    return state.get("route", QueryRoute.DOCUMENTAIRE.value)

