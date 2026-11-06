from pathlib import Path
import importlib

from evaluation.erp_benchmark.bank import load_bank
from evaluation.erp_benchmark.oracle import _date_variants, evaluate_plan
from evaluation.erp_benchmark.plans import PLANS
from evaluation.erp_benchmark.runner import score_answer


ROOT = Path(__file__).resolve().parents[1]
BANK = ROOT / ".scratch" / "miro_ai_eval_authoring" / "draft_erp_questions.jsonl"


class FakeExecutor:
    def __init__(self):
        self.rows = {
            "account.move": [
                {"id": 1, "state": "posted", "name": "M001", "partner_id": [2, "Acme"], "amount_total": 12.5, "currency_id": [1, "EUR"]},
                {"id": 2, "state": "posted", "name": "M002", "partner_id": [2, "Acme"], "amount_total": 7.5, "currency_id": [1, "EUR"]},
            ],
            "res.company": [{"id": 1, "name": "Miro", "currency_id": [1, "EUR"], "fiscalyear_last_month": "12", "period_lock_date": False}],
            "res.currency": [{"id": 1, "display_name": "EUR", "name": "EUR"}],
            "res.partner": [{"id": 2, "display_name": "Acme", "name": "Acme"}],
            "sale.order": [{"id": 3, "name": "SO001", "partner_id": [2, "Acme"]}],
        }

    def execute(self, model, method, args, kwargs=None):
        kwargs = kwargs or {}
        if method == "fields_get":
            fields = args[0] if args else []
            types = {
                "state": {"type": "selection", "selection": [["posted", "Posted"]]},
                "amount_total": {"type": "monetary", "selection": False},
                "currency_id": {"type": "many2one", "relation": "res.currency", "selection": False},
                "name": {"type": "char", "selection": False},
                "partner_id": {"type": "many2one", "relation": "res.partner", "selection": False},
                "fiscalyear_last_month": {"type": "selection", "selection": [["12", "December"]]},
            }
            return {field: types.get(field, {"type": "char", "selection": False}) for field in fields}
        if method == "search_count":
            return len(self.rows.get(model, []))
        if method == "search_read":
            rows = self.rows.get(model, [])
            return [{field: row.get(field) for field in kwargs.get("fields", [])} | {"id": row["id"]} for row in rows[:kwargs.get("limit", len(rows))]]
        if method == "read":
            ids = set(args[0])
            return [{field: row.get(field) for field in kwargs.get("fields", [])} | {"id": row["id"]} for row in self.rows.get(model, []) if row["id"] in ids]
        raise AssertionError((model, method, args, kwargs))


def test_new_bank_is_valid_and_oracle_plans_cover_every_question():
    questions, digest = load_bank(BANK)
    assert len(questions) == 100
    assert digest
    assert {item["id"] for item in questions} == set(PLANS)


def test_count_oracle_is_runtime_value_not_a_fixture():
    result = evaluate_plan(FakeExecutor(), PLANS["ERP-C-001"])
    assert result.value == 2
    assert result.expected_groups == (("2",),)


def test_aggregate_oracle_buckets_by_currency_but_expects_only_the_amount():
    result = evaluate_plan(FakeExecutor(), PLANS["ERP-C-003"])
    assert result.value[0]["currency"] == "EUR"
    assert len(result.expected_groups) == 1 and "EUR" not in result.expected_groups[0]
    assert {"20", "20,0", "20.00"} <= set(result.expected_groups[0])
    assert score_answer("EUR", result)["complete"] is False


def test_selection_value_oracle_exposes_key_and_runtime_label():
    result = evaluate_plan(FakeExecutor(), PLANS["ERP-V-004"])
    assert set(("12", "December")) <= set(result.expected_groups[0])


def test_list_oracle_expects_the_selection_label_and_no_currency():
    result = evaluate_plan(FakeExecutor(), PLANS["ERP-L-001"])
    assert not any("EUR" in group for group in result.expected_groups)
    state_plan = {"kind": "rows", "model": "account.move", "domain": [], "fields": ["name", "state"]}
    groups = evaluate_plan(FakeExecutor(), state_plan).row_groups[0]
    assert ("posted", "Posted") == groups[1]


def test_oracle_accepts_one_decimal_amounts_and_long_french_dates():
    result = evaluate_plan(FakeExecutor(), PLANS["ERP-L-001"])
    assert any("12,5" in group for group in result.expected_groups)
    assert "1 janvier 2026" in _date_variants("2026-01-01") and "01 janvier 2026" in _date_variants("2026-01-01")
    assert "décembre" in evaluate_plan(FakeExecutor(), PLANS["ERP-V-004"]).expected_groups[0]


def test_an_unset_value_is_scored_by_false_or_a_plain_none():
    result = evaluate_plan(FakeExecutor(), PLANS["ERP-V-006"])
    assert result.value is False
    assert score_answer("Aucune date de verrouillage n'est définie.", result)["complete"] is True
    assert score_answer("La date de verrouillage est le 3 mars 2026.", result)["complete"] is False


def test_posted_entries_oracle_is_shared_by_the_global_and_the_profile_question():
    assert PLANS["ERP-P-003"] == PLANS["ERP-C-001"]


def test_zero_count_is_scored_by_the_number_or_a_plain_none_but_not_by_an_abstention():
    executor = FakeExecutor()
    executor.rows["account.move"] = []
    result = evaluate_plan(executor, PLANS["ERP-N-001"])
    assert result.empty and result.kind == "count"
    assert score_answer("Il n'existe aucune écriture dans ces deux statuts.", result)["complete"] is True
    assert score_answer("Il y en a 0.", result)["complete"] is True
    refusal = score_answer("La recherche n'a pas abouti : aucune catégorie ne correspond.", result)
    assert refusal["complete"] is False and refusal["abstention"] is True
    unread = score_answer("Aucun modèle ne correspond à ce terme.", result, read_data=False)
    assert unread["complete"] is False


def test_empty_list_answer_is_scored_as_an_empty_result():
    executor = FakeExecutor()
    executor.rows["account.move"] = []
    result = evaluate_plan(executor, PLANS["ERP-L-001"])
    assert score_answer("Aucune facture ne correspond.", result)["complete"] is True


def test_relation_plan_has_no_numeric_id_in_public_rows():
    result = evaluate_plan(FakeExecutor(), PLANS["ERP-R-001"])
    assert all("partner_id" not in str(row) and row["relation_1"] == [{"name": "Acme"}] for row in result.rows)


def test_relation_empty_for_every_parent_is_an_empty_result():
    result = evaluate_plan(FakeExecutor(), PLANS["ERP-R-003"])
    assert result.count == 2 and result.empty
    assert score_answer("Aucun paiement n'est lié à ces factures.", result)["complete"] is True
    assert score_answer("La recherche n'a pas abouti : aucun paiement.", result)["complete"] is False
    assert score_answer("Aucun paiement.", result, read_data=False)["complete"] is False


def test_relation_with_related_values_is_not_empty():
    result = evaluate_plan(FakeExecutor(), PLANS["ERP-R-001"])
    assert not result.empty
    assert score_answer("Aucune facture.", result)["complete"] is False


def test_model_runner_reuses_the_existing_worker_signature(monkeypatch, tmp_path):
    benchmark = importlib.import_module("scripts.run_erp_benchmark")
    worker = importlib.import_module("scripts.run_erp_model_eval")
    calls = []

    def fake_worker(*args):
        calls.append(args)
        return {"answer": "2", "tool_calls": [], "timing": {}}

    def fake_run_on_model(model, context_length, keep_loaded, execute, probes):
        execute({"model": model, "context_length": context_length})
        return 0

    monkeypatch.setattr(worker, "_run_isolated_question", fake_worker)
    monkeypatch.setattr(benchmark, "run_on_model", fake_run_on_model)
    session = type("Session", (), {
        "uid": 7, "login": "admin", "instance_fingerprint": "instance", "server_version": "17.0",
        "active_company_id": 1, "allowed_company_ids": [1, 2],
    })()
    question = {"id": "ERP-C-001", "question": "Combien ?"}
    oracle = {
        "question_id": "ERP-C-001",
        "oracle_status": "ok",
        "oracle": {"status": "ok", "kind": "count", "expected_groups": [["2"]], "row_groups": [], "value": 2, "count": 2, "rows": [], "empty": False, "reason": None},
        "bank_sha256": "bank",
        "oracle_sha256": "oracle",
    }
    records, exit_code = benchmark.run_model(
        [oracle], {question["id"]: question}, session, "secret", "qwen3:14b", None, 1,
        tmp_path / "results.jsonl", "run", 10, 32768,
    )
    assert exit_code == 0
    assert records[0]["complete"] is True
    assert calls == [("Combien ?", 7, "secret", "qwen3:14b", None, 10, 1, [1, 2])]


def _company_context(rows):
    from evaluation.erp_benchmark.runner import XmlRpcReadSession

    session = object.__new__(XmlRpcReadSession)
    session.uid = 7
    session._execute_raw = lambda *args, **kwargs: rows
    return session._load_company_context()


def test_active_company_comes_first_in_the_allowed_companies():
    assert _company_context([{"company_id": [1, "A"], "company_ids": [2, 1]}]) == (1, [1, 2])
    assert _company_context([{"company_id": [3, "C"], "company_ids": [2, 1]}]) == (3, [3, 2, 1])
    assert _company_context([{"company_id": False, "company_ids": [2, 1]}]) == (None, [2, 1])
