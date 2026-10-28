# -*- coding: utf-8 -*-
import pytest
from unittest.mock import patch
from core.graph.graph import route
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
     "donnees_erp"),
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
