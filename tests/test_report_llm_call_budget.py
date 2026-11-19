import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "report_llm_call_budget.py"


def _load_report_module():
    spec = importlib.util.spec_from_file_location("report_llm_call_budget_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _summary(branch, llm_calls):
    return {
        "record_type": "SUMMARY", "trace_id": f"t{llm_calls}", "timestamp": "2026-11-19T00:00:00+00:00",
        "branch": branch, "question_preview": "q", "hop_count": 0, "llm_call_count": llm_calls,
        "total_time_ms": 1.0, "hop_cap_hit": False, "fallback_reason": None, "final_message_preview": None,
    }


def test_traces_written_under_the_old_branch_name_are_counted_with_documents(tmp_path):
    log = tmp_path / "reasoning_trace.jsonl"
    log.write_text(
        "\n".join(json.dumps(record) for record in (
            _summary("documentation", 1), _summary("documents", 2), _summary("system", 3),
        )) + "\n",
        encoding="utf-8",
    )

    report = _load_report_module().build_budget_report(log)

    rows = [line for line in report.splitlines() if line.startswith("| Simple RAG (documents)")]
    assert len(rows) == 1 and "| 2 |" in rows[0]
    assert "| documentation" not in report
