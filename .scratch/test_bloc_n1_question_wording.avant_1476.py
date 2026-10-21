import json
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import run_bloc_n1_benchmark as runner

BUSINESS_BANKS = ("native_n1", "custom_b9")
TECHNICAL_IDENTIFIER = re.compile(r"\b[a-z]+_[a-z_]+\b|\b[a-z]+\.[a-z_.]+\b|=\s*\w+")


def _questions(bank):
    path = runner.discover_banks()[bank]
    return json.loads(path.read_text(encoding="utf-8"))["questions"]


def _business_cases():
    return [(bank, item) for bank in BUSINESS_BANKS for item in _questions(bank)]


@pytest.mark.parametrize("bank,item", _business_cases(), ids=lambda v: v["id"] if isinstance(v, dict) else v)
def test_business_question_has_no_technical_identifier(bank, item):
    assert not TECHNICAL_IDENTIFIER.search(item["business_question"])


@pytest.mark.parametrize("bank", BUSINESS_BANKS)
def test_every_item_has_the_runner_fields(bank):
    required = {"id", "module", "capability", "difficulty", "question", "business_question",
                "reference_answer", "verification"}
    assert all(required <= item.keys() for item in _questions(bank))


def test_banks_are_discovered_and_ids_are_unique(monkeypatch):
    monkeypatch.setattr(runner.settings, "OCA_SAMPLE_ADDONS_PATH", "/any", raising=False)
    questions, meta = runner.load_questions()
    ids = [q["id"] for q in questions]
    assert len(ids) == len(set(ids))
    assert {"native_n1", "custom_b9", "oca_p3_1"} <= {q["bank"] for q in questions}
    assert "custom_asset_loan" in meta["modules_covered"]


def test_bank_with_unmet_requirement_is_skipped(monkeypatch):
    monkeypatch.setattr(runner.settings, "OCA_SAMPLE_ADDONS_PATH", None, raising=False)
    questions, _ = runner.load_questions()
    assert "oca_p3_1" not in {q["bank"] for q in questions}


def test_filters_select_by_id_module_and_bank():
    by_id, _ = runner.load_questions(["CNA-Q1"])
    assert [q["id"] for q in by_id] == ["CNA-Q1"]
    by_module, _ = runner.load_questions(module="custom_asset_loan")
    assert {q["module"] for q in by_module} == {"custom_asset_loan"}
    by_bank, _ = runner.load_questions(banks=["custom_b9"])
    assert {q["bank"] for q in by_bank} == {"custom_b9"}


def test_select_question_defaults_to_business_wording():
    item = {"question": "technical", "business_question": "business"}
    assert runner.select_question(item) == "business"
    assert runner.select_question(item, technical=True) == "technical"


def test_select_question_falls_back_when_business_wording_is_missing():
    assert runner.select_question({"question": "technical"}) == "technical"


def test_bank_language_reaches_the_agent_state():
    questions, _ = runner.load_questions(question_ids=["CNA-Q1"])
    assert runner.build_agent_state(questions[0])["language"] == "fr"


def test_agent_state_has_no_language_when_the_bank_declares_none():
    assert "language" not in runner.build_agent_state({"question": "q"})


def test_questions_with_a_missing_module_are_skipped(capsys):
    installed = {"custom_credit_note_approval", "custom_credit_note_approval_regional", "maintenance"}
    questions, _ = runner.load_questions(installed_modules=installed)
    ids = {q["id"] for q in questions}
    assert {"CNA-Q1", "MNT-Q1"} <= ids
    assert not ids & {"CNA-Q2", "CNA-Q3", "ALN-Q1"}
    assert "CNA-Q3 saute" in capsys.readouterr().out


def test_nothing_is_skipped_without_an_inventory():
    questions, _ = runner.load_questions(installed_modules=None)
    assert {"CNA-Q3", "ALN-Q1"} <= {q["id"] for q in questions}


def test_requested_id_with_a_missing_module_is_skipped_not_unknown(capsys):
    questions, _ = runner.load_questions(question_ids=["ALN-Q1"], installed_modules={"maintenance"})
    out = capsys.readouterr().out
    assert questions == [] and "ALN-Q1 saute" in out and "inconnu" not in out
