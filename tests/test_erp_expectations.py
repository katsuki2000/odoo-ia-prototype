import json
import xmlrpc.client
from pathlib import Path

import pytest

from evaluation.erp_expectations import NotApplicable, amount_variants, compute_expected

BANK = Path(__file__).resolve().parent / "erp_eval_questions.json"


def _executor(installed=True, **results):
    def execute(model, method, args, kwargs=None):
        if model == "ir.module.module":
            return int(installed)
        return results[method]

    return execute


def _question(**expectation):
    return {"requires": ["sale"], "expectation": expectation}


def test_count_expects_the_number_of_records():
    question = _question(kind="count", model="sale.order", domain=[])
    assert compute_expected(_executor(search_count=22), question) == [["22"]]


def test_count_without_record_is_not_applicable():
    question = _question(kind="count", model="sale.order", domain=[])
    with pytest.raises(NotApplicable):
        compute_expected(_executor(search_count=0), question)


def test_missing_module_is_not_applicable():
    question = _question(kind="count", model="sale.order", domain=[])
    with pytest.raises(NotApplicable, match="module sale is not installed"):
        compute_expected(_executor(installed=False, search_count=3), question)


def test_amount_accepts_every_usual_writing():
    assert amount_variants(120187.11) == ["120,187.11", "120.187,11", "120187,11", "120187.11"]
    assert {"2001", "2,001", "2.001", "2001,00", "2001.00"} <= set(amount_variants(2001.0))


def test_sum_expects_the_amount_of_a_single_currency():
    question = _question(kind="sum", model="sale.order", domain=[], field="amount_total", currency_field="currency_id")
    groups = [{"amount_total": 2001.0}]
    assert compute_expected(_executor(read_group=groups), question) == [amount_variants(2001.0)]


@pytest.mark.parametrize("groups", [[], [{"amount_total": 1.0}, {"amount_total": 2.0}]])
def test_sum_without_record_or_with_several_currencies_is_not_applicable(groups):
    question = _question(kind="sum", model="sale.order", domain=[], field="amount_total", currency_field="currency_id")
    with pytest.raises(NotApplicable):
        compute_expected(_executor(read_group=groups), question)


def test_top_expects_the_leader_and_ignores_records_without_group():
    question = _question(kind="top", model="sale.order", domain=[], groupby="partner_id", field="amount_total")
    groups = [
        {"partner_id": False, "amount_total": 900.0},
        {"partner_id": [7, "Azure Interior"], "amount_total": 300.0},
        {"partner_id": [8, "Deco Addict"], "amount_total": 120.0},
    ]
    assert compute_expected(_executor(read_group=groups), question) == [["Azure Interior"]]


def test_top_counts_records_without_measure_field():
    question = _question(kind="top", model="sale.order", domain=[], groupby="partner_id")
    groups = [{"partner_id": [7, "A"], "__count": 2}, {"partner_id": [8, "B"], "__count": 5}]
    assert compute_expected(_executor(read_group=groups), question) == [["B"]]


def test_top_with_a_tie_is_not_applicable():
    question = _question(kind="top", model="sale.order", domain=[], groupby="partner_id")
    groups = [{"partner_id": [7, "A"], "__count": 2}, {"partner_id": [8, "B"], "__count": 2}]
    with pytest.raises(NotApplicable):
        compute_expected(_executor(read_group=groups), question)


def test_odoo_refusal_is_not_applicable_with_its_message():
    def execute(model, method, args, kwargs=None):
        if model == "ir.module.module":
            return 1
        raise xmlrpc.client.Fault(1, "Traceback...\nodoo.exceptions.AccessError: no access")

    question = _question(kind="count", model="sale.order", domain=[])
    with pytest.raises(NotApplicable, match="odoo.exceptions.AccessError: no access"):
        compute_expected(execute, question)


def test_bank_questions_are_well_formed():
    questions = json.loads(BANK.read_text(encoding="utf-8"))["questions"]
    assert len({item["id"] for item in questions}) == len(questions)
    for item in questions:
        spec = item["expectation"]
        assert item["requires"] and item["question"].endswith("?")
        assert spec["kind"] in {"count", "sum", "top"}
        assert {"model", "domain"} <= spec.keys()
        assert spec["kind"] != "sum" or {"field", "currency_field"} <= spec.keys()
        assert spec["kind"] != "top" or "groupby" in spec
