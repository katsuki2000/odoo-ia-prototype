# -*- coding: utf-8 -*-
"""
Bug A / pattern H4 (todo/contexte.txt sections 93/106/107, todo/plan.md
Bloc 9 "STATUT ROUVERT"): resolved_concept was computed correctly by
route() (H1 prototype) but never consulted by the two no-signal fallback
branches, which always guessed DOCUMENTAIRE (or stuck to whatever the
previous turn's route was) even when a deterministic, zero-LLM-cost
business-term resolution (business_resolver.py) had already succeeded.
Confirmed on 5 real questions across 3 modules (01c, 03a, 03c, 04c, 05c).

Fix (already applied on disk in rag/routing.py by the time this test file
was written -- see contexte.txt for the "found already applied, catching
up on todo/rules.md's 'put everything you change in todo/contexte.txt'
discipline" note): _concept_suggests_code_intelligence(), consulted ONLY
inside the two pre-existing no-signal fallbacks. Deliberately NOT a bare
"is_resolved implies CODE_INTELLIGENCE" check -- that was found unsafe
against DOC-08 ("Quel est le délai de traitement pour une demande de mise
à disposition ?", tests/benchmark_questions.json), which resolves via the
exact same static-alias tier as the H4 questions yet is a documentary
question, not a governance one. The gate therefore requires BOTH signals:
resolved_concept.is_resolved AND a GOVERNANCE_SIGNAL_TERMS hit.

This file locks:
  1. Unit behavior of _concept_suggests_code_intelligence in isolation
     (no chunks/no graph dependency) -- the AND-gate shape itself.
  2. It stays inert whenever resolved_concept is unresolved, or governance
     vocabulary is absent, regardless of the other signal.
  3. End-to-end through route(): a real question that resolves via static
     alias ("avoir") AND carries governance vocabulary reaches
     CODE_INTELLIGENCE from the no-chunks fallback, where before this fix
     it would have defaulted to DOCUMENTAIRE.
  4. The DOC-08 counter-example itself never regresses: a real question
     that resolves via the same static-alias tier but carries no
     governance vocabulary stays out of CODE_INTELLIGENCE.
  5. It never overrides a real keyword match, mirroring the existing
     non-regression argument already made for _sticky_route_or_default /
     test_h1c_sticky_routing.py -- this gate only ever fires in the two
     branches that were already a zero-signal guess.
"""
import pytest

from core.routing import (
    route,
    _concept_suggests_code_intelligence,
    GOVERNANCE_SIGNAL_TERMS_FOLDED,
    _fold_accents,
    _VALID_ROUTES,
)
from code_intelligence.business_resolver import ResolvedConcept
from core.schemas import QueryRoute


def _route_question(question: str, chunks=None) -> str:
    state = {
        "question": question,
        "retrieved_chunks": chunks if chunks is not None else [],
        "chat_history": [],
        "timing": {},
        "last_route": None,
    }
    return route(state)["route"]


# ── _concept_suggests_code_intelligence unit behavior ──────────────────────

def test_none_concept_never_fires():
    assert _concept_suggests_code_intelligence("cet avoir echappe-t-il au controle", None) is False


def test_unresolved_concept_never_fires_even_with_governance_terms():
    concept = ResolvedConcept(user_term="avoir", is_resolved=False)
    assert _concept_suggests_code_intelligence("cet avoir echappe-t-il au controle", concept) is False


def test_resolved_concept_without_governance_terms_never_fires():
    """The DOC-08 shape: is_resolved=True via static_alias, but the
    question itself carries no governance vocabulary -- must stay False."""
    concept = ResolvedConcept(user_term="mise a disposition", resolved_models=["custom.asset.loan"], is_resolved=True)
    question_folded = _fold_accents("quel est le delai de traitement pour une demande de mise a disposition")
    assert _concept_suggests_code_intelligence(question_folded, concept) is False


def test_resolved_concept_with_governance_term_fires():
    concept = ResolvedConcept(user_term="avoir", resolved_models=["account.move"], is_resolved=True)
    question_folded = _fold_accents("cet avoir echappe-t-il au controle habituel")
    assert _concept_suggests_code_intelligence(question_folded, concept) is True


@pytest.mark.parametrize("term", ["valid", "règle", "s'applique", "échappe", "automatique", "contrôle"])
def test_every_governance_term_is_actually_in_the_folded_list(term):
    """Locks the vocabulary this gate depends on -- if any of these 5
    H4-derived terms is ever removed from GOVERNANCE_SIGNAL_TERMS_FOLDED,
    this test fails loudly instead of the gate silently going dark for
    that question family."""
    assert _fold_accents(term) in GOVERNANCE_SIGNAL_TERMS_FOLDED


# ── End-to-end through route(): the two no-signal fallback branches ───────

def test_h4_shaped_question_routes_to_code_intelligence_no_chunks():
    """Real question, real resolver (via route()'s own internal call),
    zero chunks retrieved (the "elif not chunks" branch). Matches no
    keyword in any of the 7 lists (verified: no ERP/DOC/CODE_INTEL keyword
    substring present), resolves "avoir" -> account.move via static alias,
    and carries "échappe"/"contrôle" -- must now reach CODE_INTELLIGENCE
    instead of the pre-fix DOCUMENTAIRE default."""
    result = _route_question(
        "Cet avoir échappe-t-il au contrôle habituel de l'entreprise ?",
        chunks=[],
    )
    assert result == QueryRoute.CODE_INTELLIGENCE.value


def test_doc08_shaped_question_does_not_regress_into_code_intelligence():
    """The exact counter-example this gate's own docstring cites: resolves
    via the same static-alias tier ("mise à disposition" ->
    custom.asset.loan) but asks about a documented SLA, not governance --
    must NOT be redirected to CODE_INTELLIGENCE by this fix."""
    result = _route_question(
        "Quel est le délai de traitement pour une demande de mise à disposition ?",
        chunks=[],
    )
    assert result != QueryRoute.CODE_INTELLIGENCE.value


def test_erp_ratio_fallback_branch_also_honors_the_gate():
    """The second no-signal fallback (chunks retrieved, but neither a high
    ERP ratio nor a DATA_TERMS hit) must also consult resolved_concept +
    governance vocabulary, mirroring the no-chunks branch above."""
    chunks = [
        {"document": "texte non pertinent", "metadata": {"type": "wiki"}},
        {"document": "autre texte non pertinent", "metadata": {"type": "wiki"}},
    ]
    result = _route_question(
        "Cet avoir échappe-t-il au contrôle habituel ?",
        chunks=chunks,
    )
    assert result == QueryRoute.CODE_INTELLIGENCE.value


# ── Must never override a real keyword match ───────────────────────────────

def test_real_erp_keyword_still_wins_even_if_concept_and_governance_terms_present():
    """A question matching an ERP keyword list entry must route to
    donnees_erp exactly as before, even if it happens to also resolve a
    business concept and carry governance vocabulary -- this gate only
    ever fires in the two zero-signal fallbacks, never earlier in
    route()'s precedence chain."""
    result = _route_question(
        "Quel est le montant total des avoirs, et cette règle s'applique-t-elle à tous ?",
        chunks=[],
    )
    assert result == QueryRoute.DONNEES_ERP.value


# ── The 5 real, originally-confirmed H4 questions (todo/contexte.txt) ─────
#
# Pulled verbatim (2026-08-21) from the real scripts/check_bloc9_0{1,3,4,5}_
# *_e2e.py files (NOT miro-rag/scripts/, which does not hold these -- see
# contexte.txt section 109) rather than reconstructed from memory/summary,
# per the project's own "evidence-first diagnosis" principle (todo/rules.md/
# contexte.txt). Weaker assertion than the synthetic cases above ("!=
# DOCUMENTAIRE" rather than "== CODE_INTELLIGENCE"): the H4 bug's observable
# symptom was always a wrong DOCUMENTAIRE default, so "no longer
# documentaire" is the correct regression guard here -- asserting the exact
# branch would require independently re-deriving whether each question also
# matches one of the 7 pre-existing keyword lists on its own merits (some do
# -- see the per-question notes below), which is a routing-precision
# question distinct from this fix's own scope.

_REAL_H4_QUESTIONS = [
    pytest.param(
        # 01c (todo/contexte.txt): full-pipeline phrasing from
        # check_bloc9_01_credit_note_cascade_e2e.py::check_e2e_full_pipeline
        # ('01c-vip-trap'). No ERP/DOC/CODE_INTEL keyword list entry present
        # (verified by inspection) -- reaches the no-chunks fallback
        # entirely via this fix.
        "Un avoir pour un client VIP (champ avoir_vip_exempt à True sur le "
        "partenaire) échappe-t-il au contrôle de validation à 5000€ appliqué "
        "aux autres avoirs ?",
        id="01c-vip-trap",
    ),
    pytest.param(
        # 03a (check_bloc9_03_hr_leave_workflow_e2e.py). No keyword list
        # entry present -- reaches the no-chunks fallback.
        "Pourquoi je n'arrive pas à valider ma demande de congé alors que "
        "j'ai coché 'urgente' ?",
        id="03a-business",
    ),
    pytest.param(
        # 03c (check_bloc9_03_hr_leave_workflow_e2e.py). No keyword list
        # entry present ('dépasse' alone, without '-t-il', does not match
        # THRESHOLD_QUERY_TERMS' 'dépasse-t-il'/'depasse-t-il') -- reaches
        # the no-chunks fallback.
        "Si un employé coche 'urgente' sur une demande de congé qui dépasse "
        "son solde restant, sa demande est-elle automatiquement validée, ou "
        "faut-il encore une validation supplémentaire ?",
        id="03c-urgente-trap",
    ),
    pytest.param(
        # 04c (check_bloc9_04_purchase_request_e2e.py). NOTE (2026-08-21,
        # todo/contexte.txt section 109): unlike the other 4, this question
        # contains the bare word "montant", which IS a QUANTITATIVE_TERMS
        # entry -- route()'s precedence chain reaches "has_quantitative and
        # not is_threshold_query" (-> DONNEES_ERP) BEFORE the no-signal
        # fallback this fix touches, so on the CURRENT wording of this
        # script's question this fix may not be the one keeping it out of
        # DOCUMENTAIRE (DONNEES_ERP's own precedence already would). Kept in
        # this file for its documented history as one of the 5 originally-
        # confirmed H4 cases, but flagged here rather than silently assumed
        # -- only a live run (not yet done) confirms which branch it
        # actually reaches today.
        "Un utilisateur membre du groupe purchase_manager peut-il, à lui "
        "seul, valider n'importe quelle demande d'achat quel que soit son "
        "montant ?",
        id="04c-manager-trap",
    ),
    pytest.param(
        # 05c (check_bloc9_05_asset_loan_e2e.py, 'bloc9-05c-no-link-trap').
        # No keyword list entry present -- reaches the no-chunks fallback.
        "Si une mise à disposition de matériel n'est reliée à aucune "
        "demande d'achat, la règle de séparation des rôles (bénéficiaire "
        "différent du demandeur) s'applique-t-elle quand même, quel que "
        "soit le montant du matériel ?",
        id="05c-no-link-trap",
    ),
]


@pytest.mark.parametrize("question", _REAL_H4_QUESTIONS)
def test_real_h4_question_no_longer_defaults_to_documentaire(question):
    """Regression guard using the actual, originally-confirmed H4 question
    text (not a synthetic stand-in) -- the bug's own symptom was always a
    wrong DOCUMENTAIRE default, so this is the correct assertion shape for
    all 5, including 04c whose exact branch is noted above as still
    needing live confirmation."""
    result = _route_question(question, chunks=[])
    assert result != QueryRoute.DOCUMENTAIRE.value
