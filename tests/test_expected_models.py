"""Modeles attendus et classement d'exactitude (journal D-14) : hermetique, aucun serveur."""

import json
from pathlib import Path

import pytest

from core.evaluation.expected_models import (
    ABSTENTION, EXACT, PARTIAL, WRONG, DEFAULT_PATH, classify_resolution, load_expected_models)

ROOT = Path(__file__).resolve().parents[1]
BANKS = ("custom_b9_question_bank.json", "native_n1_question_bank.json")


def test_exact_requires_all_expected_and_nothing_outside_tolerance():
    exp, tol = frozenset({"stock.picking"}), frozenset({"stock.backorder.confirmation"})
    assert classify_resolution(["stock.picking"], exp, tol) == EXACT
    assert classify_resolution(["stock.picking", "stock.backorder.confirmation"], exp, tol) == EXACT
    assert classify_resolution(["stock.backorder.confirmation"], exp, tol) == WRONG      # toleré jamais seul
    assert classify_resolution(["stock.picking", "stock.move"], exp, tol) == WRONG        # modele en trop
    assert classify_resolution([], exp, tol) == ABSTENTION


def test_partial_when_only_some_expected_models_are_present():
    exp = frozenset({"a.model", "b.model"})
    assert classify_resolution(["a.model"], exp) == PARTIAL
    assert classify_resolution(["a.model", "b.model"], exp) == EXACT
    assert classify_resolution(["c.model"], exp) == WRONG


def test_native_wizard_instead_of_the_model_is_wrong_even_though_resolved():
    assert classify_resolution(["validate.account.move"], frozenset({"account.move"})) == WRONG


def _bank_ids():
    ids = set()
    for name in BANKS:
        data = json.loads((ROOT / "tests" / name).read_text(encoding="utf-8"))
        ids |= {q["id"] for q in (data["questions"] if isinstance(data, dict) else data)}
    return ids


def test_shipped_file_is_consistent():
    expected, tolerated = load_expected_models()
    assert expected and DEFAULT_PATH.exists()
    assert set(expected) <= _bank_ids()
    for qid, models in expected.items():
        assert models, qid
        assert not (models & tolerated[qid]), qid
        assert all(m.count(".") >= 1 and m == m.strip() for m in models | tolerated[qid]), qid


def test_every_entry_is_a_list_of_model_names():
    data = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
    for qid, models in data.items():
        if not qid.startswith("_"):
            assert isinstance(models, list) and all(isinstance(m, str) for m in models)
