# -*- coding: utf-8 -*-
import pytest
from core.graph import (
    _fold_accents,
    ERP_KEYWORDS, ERP_KEYWORDS_FOLDED,
    CODE_INTEL_KEYWORDS, CODE_INTEL_KEYWORDS_FOLDED,
    DOC_KEYWORDS, DOC_KEYWORDS_FOLDED,
    DOC_ANCHORS, DOC_ANCHORS_FOLDED,
    THRESHOLD_QUERY_TERMS, THRESHOLD_QUERY_TERMS_FOLDED,
    route,
)


def _route_question(question: str) -> str:
    """Same helper as test_j18_routing_fewshot.py: run route() with empty
    chunks/history, return only the route decision."""
    state = {
        "question": question,
        "retrieved_chunks": [],
        "chat_history": [],
        "timing": {},
    }
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
    through every branch to the documentaire default instead."""
    accented = _route_question("Et pour cette année ?")
    unaccented = _route_question("Et pour cette annee ?")
    assert accented == unaccented == "donnees_erp"


def test_unrelated_followup_with_no_keyword_at_all_is_still_unresolved():
    """Distinct, still-open gap: a follow-up with NO keyword (accented or
    not) is not and cannot be fixed by accent-folding alone -- it still
    falls to the documentaire default. This is the real remaining H1c
    question (session/conversational context), not an accent artifact.
    Asserted explicitly so a future change that silently "fixes" this via
    an unrelated mechanism gets noticed here, not assumed."""
    assert _route_question("Et pour Lyon ?") == "documentaire"


# ── One genuinely diagnostic accented/unaccented pair per affected list --
# "diagnostic" here means the UNACCENTED form actually lands on a
# DIFFERENT branch than the accented form before this fix (not just on
# the same documentaire default every unmatched question falls to
# anyway) -- otherwise the pair doesn't actually exercise the bug.

@pytest.mark.parametrize("accented, unaccented, expected_route", [
    # ERP_KEYWORDS ("cette année") -- covered above in its own dedicated
    # test since it's the exact case that surfaced the bug live.

    # CODE_INTEL_KEYWORDS ("droits d'accès"): unaccented alone matched
    # nothing before the fix (documentaire default) -- accented matched
    # code_intelligence directly.
    ("Quelle est la disponibilité en droits d'accès pour ce module ?",
     "Quelle est la disponibilite en droits d'acces pour ce module ?",
     "code_intelligence"),
    # DOC_ANCHORS ("où est documenté") combined with a quantitative term:
    # unaccented alone lost the anchor, so is_hybrid was never true and
    # the quantitative term alone routed to donnees_erp instead of hybride.
    ("Où est documenté combien de tickets sont encore en cours ?",
     "Ou est documente combien de tickets sont encore en cours ?",
     "hybride"),
    # DOC_KEYWORDS ("quel est le rôle") combined with a quantitative term:
    # same is_hybrid mechanism as above, different source list.
    ("Quel est le rôle du responsable et combien de tickets sont en cours ?",
     "Quel est le role du responsable et combien de tickets sont en cours ?",
     "hybride"),
])
def test_accented_and_unaccented_variants_route_identically(accented, unaccented, expected_route):
    route_accented = _route_question(accented)
    route_unaccented = _route_question(unaccented)
    assert route_accented == route_unaccented == expected_route