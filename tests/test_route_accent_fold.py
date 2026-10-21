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
from core.routing.source_selection import SourceSelection


def _route_question(question: str, selection: SourceSelection) -> str:
    """Run route() with the source selector replaced by a fixed signal."""
    state = {
        "question": question,
        "retrieved_chunks": [],
        "chat_history": [],
        "timing": {},
    }
    with patch("core.routing.routing.select_source", return_value=selection):
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


# ── Routing consumes the selector signal; accents never change the decision ──

def test_followup_with_no_source_signal_asks_for_clarification():
    uncertain = SourceSelection(source="uncertain", confidence=0.0)
    assert _route_question("Et pour Lyon ?", uncertain) == "source_clarification"


def test_low_confidence_selection_asks_for_clarification():
    weak = SourceSelection(source="documentation", confidence=0.1)
    assert _route_question("Quel est le role du responsable ?", weak) == "source_clarification"


@pytest.mark.parametrize("accented, unaccented, selection, expected_route", [
    ("Quelle est la disponibilité en droits d'accès pour ce module ?",
     "Quelle est la disponibilite en droits d'acces pour ce module ?",
     SourceSelection(source="systeme", confidence=0.9),
     "code_intelligence"),
    ("Où est documenté combien de tickets sont encore en cours ?",
     "Ou est documente combien de tickets sont encore en cours ?",
     SourceSelection(source="documentation", confidence=0.9),
     "documentaire"),
    ("Quel est le rôle du responsable et combien de tickets sont en cours ?",
     "Quel est le role du responsable et combien de tickets sont en cours ?",
     SourceSelection(source="uncertain", confidence=0.9),
     "source_clarification"),
])
def test_accented_and_unaccented_variants_route_identically(accented, unaccented, selection, expected_route):
    assert _route_question(accented, selection) == _route_question(unaccented, selection) == expected_route
