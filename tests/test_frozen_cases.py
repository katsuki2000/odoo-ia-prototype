"""Hermetic tests for the frozen evaluation case schema."""

import json
from pathlib import Path

import pytest

from core.evaluation import frozen_cases as fc
from core.evaluation.instances import InstanceSpec
from tests.frozen_case_samples import RAW, make_case

def spec(name="sales_purchase_stock", split="held_out") -> InstanceSpec:
    return InstanceSpec.from_dict({
        "name": name, "split": split, "modules": ["sale"], "language": "en_US",
        "with_demo": True, "addons": ["core"],
    })


def test_valid_case_parses():
    case = fc.FrozenCase.from_dict(RAW)
    assert case.user_context.user == "base.user_demo"
    assert case.expected_claims[0].any_of == (("read", "view"),)


@pytest.mark.parametrize("changes", [
    {"split": "other"},
    {"case_id": "Bad Id"},
    {"expected_intent": "unknown_intent"},
    {"expected_sources": ["internet"]},
    {"expected_sources": []},
    {"expected_objects": ["sale.order"]},
    {"abstention_rule": "maybe"},
    {"question": "  "},
    {"user_context": {**RAW["user_context"], "user": "7"}},
    {"user_context": {**RAW["user_context"], "language": "french"}},
    {"ground_truth": {"author": "x", "method": "system_output"}},
    {"acceptable_evidence": []},
    {"expected_claims": []},
])
def test_invalid_cases_are_rejected(changes):
    with pytest.raises(ValueError):
        fc.FrozenCase.from_dict(make_case(**changes))


def test_claim_needs_a_matching_term_and_unique_ids():
    with pytest.raises(ValueError):
        fc.ExpectedClaim.from_dict({"claim_id": "c", "statement": "s"})
    duplicated = RAW["expected_claims"] * 2
    with pytest.raises(ValueError):
        fc.FrozenCase.from_dict(make_case(expected_claims=duplicated))


def test_abstention_cases_need_no_claims():
    case = fc.FrozenCase.from_dict(make_case(abstention_rule="must_clarify", expected_claims=[], acceptable_evidence=[]))
    assert case.abstention_rule == "must_clarify"


def test_freeze_is_independent_of_order_and_tracks_content():
    other = make_case(case_id="another_case")
    first = fc.freeze_dataset([RAW, other], 1)
    second = fc.freeze_dataset([other, RAW], 1)
    assert first == second
    changed = fc.freeze_dataset([RAW, make_case(case_id="another_case", question="Different?")], 1)
    assert changed["digest"] != first["digest"]


def test_duplicate_case_ids_are_rejected():
    with pytest.raises(ValueError):
        fc.freeze_dataset([RAW, RAW], 1)


def test_load_detects_modification_without_refreeze(tmp_path):
    path = tmp_path / "cases.json"
    fc.write_dataset(fc.freeze_dataset([RAW], 1), path)
    assert fc.load_dataset(path).version == 1
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["cases"][0]["question"] = "Tampered?"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        fc.load_dataset(path)


def test_check_against_instances():
    dataset = fc.dataset_from_payload(fc.freeze_dataset([RAW], 1))
    fc.check_against_instances(dataset, [spec()])
    with pytest.raises(ValueError):
        fc.check_against_instances(dataset, [spec(split="calibration")])
    with pytest.raises(ValueError):
        fc.check_against_instances(dataset, [spec(name="other")])


def test_split_cases():
    dataset = fc.dataset_from_payload(fc.freeze_dataset([RAW, make_case(case_id="cal", split="calibration")], 1))
    assert [case.case_id for case in fc.split_cases(dataset, "calibration")] == ["cal"]
    with pytest.raises(ValueError):
        fc.split_cases(dataset, "other")


def test_shipped_dataset_is_valid_and_consistent():
    root = Path(__file__).resolve().parent.parent / "core" / "evaluation" / "protocol"
    from core.evaluation.instances import load_specs

    dataset = fc.load_dataset(root / "frozen_cases.json")
    fc.check_against_instances(dataset, load_specs(root / "instances.json"))
