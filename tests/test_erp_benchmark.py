from pathlib import Path
import importlib

from evaluation.erp_benchmark.bank import load_bank
from evaluation.erp_benchmark.oracle import evaluate_plan
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
            "res.company": [{"id": 1, "name": "Miro", "currency_id": [1, "EUR"], "fiscalyear_last_month": "12"}],
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


def test_aggregate_oracle_keeps_the_currency_with_the_total():
    result = evaluate_plan(FakeExecutor(), PLANS["ERP-C-003"])
    assert result.value[0]["currency"] == "EUR"
    assert any("20.00" in group for group in result.expected_groups)


def test_selection_value_oracle_exposes_key_and_runtime_label():
    result = evaluate_plan(FakeExecutor(), PLANS["ERP-V-004"])
    assert set(("12", "December")) <= set(result.expected_groups[0])


def test_empty_list_answer_is_scored_as_an_empty_result():
    executor = FakeExecutor()
    executor.rows["account.move"] = []
    result = evaluate_plan(executor, PLANS["ERP-L-001"])
    assert score_answer("Aucune facture ne correspond.", result)["complete"] is True


def test_relation_plan_has_no_numeric_id_in_public_rows():
    result = evaluate_plan(FakeExecutor(), PLANS["ERP-R-001"])
    assert all("partner_id" not in str(row) and row["relation_1"] == [{"name": "Acme"}] for row in result.rows)


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
