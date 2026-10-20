import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import run_bloc_n1_benchmark as runner
from core.evaluation.resolution_score import ABSTAINED, EXACT, UNSCORED, WRONG, score_resolution

ITEM = {"expected_models": ["stock.picking"], "tolerated_models": ["stock.backorder.confirmation"]}


@pytest.mark.parametrize("models, verdict", [
    (["stock.picking"], EXACT),
    (["stock.picking", "stock.backorder.confirmation"], EXACT),
    (["stock.backorder.confirmation"], WRONG),
    (["stock.picking", "validate.account.move"], WRONG),
    (["validate.account.move"], WRONG),
    ([], ABSTAINED),
])
def test_score_resolution(models, verdict):
    assert score_resolution(ITEM, models) == verdict


def test_question_without_ground_truth_is_unscored():
    assert score_resolution({}, ["account.move"]) == UNSCORED
    assert score_resolution({"expected_models": []}, []) == UNSCORED


def test_banks_ground_truth_is_well_formed():
    questions, _ = runner.load_questions()
    scored = [q for q in questions if q.get("expected_models")]
    assert {"CNA-Q1", "HRL-Q2", "PUR-Q1", "STK-Q2"} <= {q["id"] for q in scored}
    for question in scored:
        for key in ("expected_models", "tolerated_models"):
            values = question.get(key, [])
            assert isinstance(values, list) and all(isinstance(v, str) and v for v in values), question["id"]
        assert not set(question["expected_models"]) & set(question.get("tolerated_models", [])), question["id"]


@pytest.mark.parametrize("bank", ["custom_b9", "native_n1"])
def test_every_question_of_the_scored_banks_has_ground_truth(bank):
    import json
    data = json.loads((ROOT / "tests" / f"{bank}_question_bank.json").read_text(encoding="utf-8"))
    assert [q["id"] for q in data["questions"] if not q.get("expected_models")] == []
