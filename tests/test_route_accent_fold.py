# -*- coding: utf-8 -*-
import pytest
from unittest.mock import patch
from core.graph.graph import (
    _fold_accents,
    ERP_KEYWORDS, ERP_KEYWORDS_FOLDED,
    CODE_INTEL_KEYWORDS, CODE_INTEL_KEYWORDS_FOLDED,
    DOC_KEYWORDS, DOC_KEYWORDS_FOLDED,
    DOC_ANCHORS, DOC_ANCHORS_FOLDED,
    THRESHOLD_QUERY_TERMS, THRESHOLD_QUERY_TERMS_FOLDED,
    route,
)
from code_intelligence.agent.investigation_schemas import QuestionIntent


def _route_question(question: str, mocked_intent: QuestionIntent) -> str:
    """Same helper as test_j18_routing_fewshot.py: run route() with empty
    chunks/history, return only the route decision.

    Cluster B fix (todo/contexte.txt sections 430-433): route() now calls
    resolve_question_intent() (code_intelligence/investigation/llm.py),
    which attempts a real, bounded LLM classifier
    (classify_question_intent_llm) BEFORE falling back to the deterministic
    keyword classifier these tests originally locked in. Left unmocked,
    every test in this file depended on live network access to the inference server and a
    non-deterministic classification -- not a unit test anymore. Per the
    explicit decision (section 433): mock classify_question_intent_llm with
    an EXPLICIT intent matching the classification the production LLM is
    expected to return for that question (not a reversion to the
    deterministic fallback -- the mock IS the LLM-first call site, just
    made deterministic for the test).
    """
    state = {
        "question": question,
        "retrieved_chunks": [],
        "chat_history": [],
        "timing": {},
    }
    with patch(
        "code_intelligence.agent.investigation_planner.classify_question_intent_llm",
        return_value=mocked_intent,
    ):
        return route(state)["route"]


# ── _fold_accents unit behavior ───────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("cette année", "cette annee"),
    ("cette annee", "cette annee"),  # already unaccented -> no-op
    ("règle d'enregistrement", "regle d'enregistrement"),
    ("où est documenté", "ou est documente"),
    ("dépasse-t-il", "depasse-t-il"),
    ("", ""),
    ("no accents here", "no accents here"),
])
def test_fold_accents_known_cases(raw, expected):
    assert _fold_accents(raw) == expected


def test_fold_accents_is_idempotent():
    """Folding an already-folded string must be a no-op -- guards against a
    future change to _fold_accents accidentally becoming non-deterministic
    across repeated application (e.g. if NFD/NFC handling changes)."""
    for kw in ERP_KEYWORDS + CODE_INTEL_KEYWORDS + DOC_KEYWORDS:
        once = _fold_accents(kw)
        twice = _fold_accents(once)
        assert once == twice


def test_folded_lists_are_precomputed_and_match_source_length():
    """*_FOLDED lists must stay in lockstep with their source lists (same
    length, same order) -- catches a future edit to one list without the
    other if someone bypasses _fold_keywords()."""
    assert len(ERP_KEYWORDS_FOLDED) == len(ERP_KEYWORDS)
    assert len(CODE_INTEL_KEYWORDS_FOLDED) == len(CODE_INTEL_KEYWORDS)
    assert len(DOC_KEYWORDS_FOLDED) == len(DOC_KEYWORDS)
    assert len(DOC_ANCHORS_FOLDED) == len(DOC_ANCHORS)
    assert len(THRESHOLD_QUERY_TERMS_FOLDED) == len(THRESHOLD_QUERY_TERMS)


# ── The exact regression case that surfaced the bug ───────────────────────

def test_accented_and_unaccented_erp_keyword_route_identically():
    """'cette année' (ERP_KEYWORDS, accented) and 'cette annee' (same
    phrase, no accent) must now produce the SAME route. Before this fix,
    only the accented form matched -- the unaccented form silently fell
    through every branch to the documentaire default instead.

    Mocked intent: ERP_DATA_QUERY -- the production LLM classifier is
    expected to recognize a live-data aggregation question regardless of
    accent, matching INTENT_TO_ROUTE's mapping to donnees_erp."""
    accented = _route_question("Et pour cette année ?", QuestionIntent.ERP_DATA_QUERY)
    unaccented = _route_question("Et pour cette annee ?", QuestionIntent.ERP_DATA_QUERY)
    assert accented == unaccented == "donnees_erp"


def test_unrelated_followup_with_no_keyword_at_all_is_still_unresolved():
    """Distinct, still-open gap: a follow-up with NO keyword (accented or
    not) is not and cannot be fixed by accent-folding alone -- it still
    falls to the documentaire default. This is the real remaining H1c
    question (session/conversational context), not an accent artifact.
    Asserted explicitly so a future change that silently "fixes" this via
    an unrelated mechanism gets noticed here, not assumed.

    Mocked intent: DOCUMENTARY_POLICY -- the production LLM's own "nothing
    more specific matched" catch-all for a question with zero business/
    technical signal, same semantic bucket the deterministic classifier's
    step 9 default used to cover."""
    assert _route_question("Et pour Lyon ?", QuestionIntent.DOCUMENTARY_POLICY) == "documentaire"


# ── One genuinely diagnostic accented/unaccented pair per affected list --
# "diagnostic" here means the UNACCENTED form actually lands on a
# DIFFERENT branch than the accented form before this fix (not just on
# the same documentaire default every unmatched question falls to
# anyway) -- otherwise the pair doesn't actually exercise the bug.

@pytest.mark.parametrize("accented, unaccented, mocked_intent, expected_route", [
    # ERP_KEYWORDS ("cette année") -- covered above in its own dedicated
    # test since it's the exact case that surfaced the bug live.

    # CODE_INTEL_KEYWORDS ("droits d'accès"): a governance/access question,
    # LLM classifier expected to return GOVERNANCE_SECURITY -> maps
    # directly to code_intelligence via INTENT_TO_ROUTE, independent of
    # accent folding (the mock removes the folding question from the LLM
    # call entirely -- accent-insensitivity is now the LLM's job, not this
    # keyword list's; this test now only locks that route()'s OWN
    # downstream wiring is accent-independent, not the classifier).
    ("Quelle est la disponibilité en droits d'accès pour ce module ?",
     "Quelle est la disponibilite en droits d'acces pour ce module ?",
     QuestionIntent.GOVERNANCE_SECURITY,
     "code_intelligence"),
    # DOC_ANCHORS ("où est documenté") combined with a quantitative term:
    # DOCUMENTARY_POLICY intent + the deterministic HYBRIDE layer (still
    # keyword/anchor-based, unaffected by the LLM classifier) promotes it
    # to hybride when a quantitative term also co-occurs.
    ("Où est documenté combien de tickets sont encore en cours ?",
     "Ou est documente combien de tickets sont encore en cours ?",
     QuestionIntent.DOCUMENTARY_POLICY,
     "hybride"),
    # DOC_KEYWORDS ("quel est le rôle") combined with a quantitative term:
    # same HYBRIDE-layer mechanism as above, different source list.
    ("Quel est le rôle du responsable et combien de tickets sont en cours ?",
     "Quel est le role du responsable et combien de tickets sont en cours ?",
     QuestionIntent.DOCUMENTARY_POLICY,
     "hybride"),
])
def test_accented_and_unaccented_variants_route_identically(accented, unaccented, mocked_intent, expected_route):
    route_accented = _route_question(accented, mocked_intent)
    route_unaccented = _route_question(unaccented, mocked_intent)
    assert route_accented == route_unaccented == expected_route
