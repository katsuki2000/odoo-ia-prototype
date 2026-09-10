"""
code_intelligence/tests/test_j46_j48_reasoning_trace.py

Unit tests for  /   + LLM-call budget comparison
across the three RAG branches, and the per-question hop cap guardrail).

Distinct from test_bloc10_incremental_event_logging.py , which tests KNOWLEDGE GRAPH staleness/recalculation events, not
agent reasoning.
"""

import pytest

from core.session.reasoning_trace_logger import (
    ReasoningTraceLogger,
    MAX_HOPS_PER_QUESTION,
    new_trace_id,
)


def test_j46_new_trace_id_is_unique():
    """J46: trace ids must be short and effectively unique per question."""
    ids = {new_trace_id() for _ in range(1000)}
    assert len(ids) == 1000
    assert all(len(i) == 12 for i in ids)


def test_j46_log_hop_writes_indexed_jsonl_record(tmp_path):
    """J46-J47: a composite tool call (name + args + observation + timing) is
    appended to the JSONL log, indexed by trace_id + hop_index so the
    reasoning path can be reconstructed post-hoc."""
    log_file = tmp_path / "reasoning_trace.jsonl"
    logger = ReasoningTraceLogger(log_filepath=log_file)
    trace_id = new_trace_id()

    hop = logger.log_hop(
        trace_id=trace_id,
        hop_index=0,
        tool_name="analyze_security_locks",
        tool_args={"model_name": "account.move"},
        observation="[Confiance: HIGH] 2 verrous detectes.",
        elapsed_ms=142.7,
    )

    assert log_file.exists()
    assert hop.trace_id == trace_id
    assert hop.tool_name == "analyze_security_locks"
    assert hop.elapsed_ms == 142.7

    records = logger.read_recent(limit=5)
    assert len(records) == 1
    assert records[0]["record_type"] == "HOP"
    assert records[0]["tool_args"] == {"model_name": "account.move"}


def test_j47_read_trace_reconstructs_full_reasoning_path(tmp_path):
    """J47: read_trace(trace_id) returns every HOP for that question in
    call order, followed by its closing SUMMARY -- the actual
    'chemin de raisonnement... indexe et lisible en debug post-hoc'
    required by the plan, not just aggregate timing numbers."""
    log_file = tmp_path / "reasoning_trace.jsonl"
    logger = ReasoningTraceLogger(log_filepath=log_file)
    trace_id = new_trace_id()
    other_trace_id = new_trace_id()

    # Interleave two different questions' traces in the same file, as would
    # happen under real concurrent traffic -- read_trace must still isolate
    # the requested one.
    logger.log_hop(trace_id, 0, "who_has_access_to", {"model_name": "account.move"}, "obs1", 10.0)
    logger.log_hop(other_trace_id, 0, "get_total_sales", {}, "obs_other", 5.0)
    logger.log_hop(trace_id, 1, "evaluate_record_rules", {"model_name": "account.move"}, "obs2", 20.0)
    logger.log_summary(
        trace_id=trace_id, branch="code_intelligence", question="Qui peut approuver un avoir ?",
        hop_count=2, llm_call_count=3, total_time_ms=1500.0,
    )
    logger.log_summary(
        trace_id=other_trace_id, branch="donnees_erp", question="Combien de ventes ce mois ?",
        hop_count=1, llm_call_count=1, total_time_ms=300.0,
    )

    path = logger.read_trace(trace_id)
    assert len(path) == 3  # 2 hops + 1 summary
    assert [r["record_type"] for r in path] == ["HOP", "HOP", "SUMMARY"]
    assert [r["hop_index"] for r in path[:2]] == [0, 1]
    assert path[2]["llm_call_count"] == 3
    assert all(r["trace_id"] == trace_id for r in path)


def test_j48_hop_cap_matches_ci_max_hops():
    """J48: the generic hop-cap guardrail constant must stay in sync with
    rag.graph's CI_MAX_HOPS -- both express the same per-question budget."""
    from core.graph.graph import CI_MAX_HOPS
    assert MAX_HOPS_PER_QUESTION == CI_MAX_HOPS


def test_j48_summary_flags_hop_cap_hit(tmp_path):
    """J48: log_summary must correctly flag whether the per-question hop
    cap guardrail was actually reached, not just record the raw count."""
    log_file = tmp_path / "reasoning_trace.jsonl"
    logger = ReasoningTraceLogger(log_filepath=log_file)

    under_cap = logger.log_summary(
        trace_id=new_trace_id(), branch="code_intelligence", question="q1",
        hop_count=2, llm_call_count=3, total_time_ms=800.0, hop_cap=4,
    )
    at_cap = logger.log_summary(
        trace_id=new_trace_id(), branch="code_intelligence", question="q2",
        hop_count=4, llm_call_count=5, total_time_ms=1200.0, hop_cap=4,
    )

    assert under_cap.hop_cap_hit is False
    assert at_cap.hop_cap_hit is True


def test_j48_llm_call_budget_report_aggregates_by_branch(tmp_path):
    """J48: the budget report script must chiffrer (mean/median/max)
    llm_call_count and hop_count PER BRANCH from real recorded traces --
    this is the 'nombre d'appels LLM par question vs RAG simple et
    Function Calling' comparison the plan requires."""
    import sys
    from pathlib import Path

    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from report_llm_call_budget import build_budget_report

    log_file = tmp_path / "reasoning_trace.jsonl"
    logger = ReasoningTraceLogger(log_filepath=log_file)

    # documentaire: cheap, 0 hops, 1 LLM call
    logger.log_summary(new_trace_id(), "documentaire", "q_doc", 0, 1, 600.0)
    logger.log_summary(new_trace_id(), "documentaire", "q_doc2", 0, 1, 550.0)
    # donnees_erp: a couple of tool hops, more LLM calls
    logger.log_summary(new_trace_id(), "donnees_erp", "q_erp", 2, 3, 4200.0, hop_cap=6)
    # code_intelligence: most expensive, one hits the cap
    logger.log_summary(new_trace_id(), "code_intelligence", "q_ci1", 4, 6, 9000.0, hop_cap=4)
    logger.log_summary(new_trace_id(), "code_intelligence", "q_ci2", 1, 2, 3000.0, hop_cap=4)

    report = build_budget_report(log_filepath=log_file)

    assert "RAG simple (documentaire)" in report
    assert "Function Calling (donnees_erp)" in report
    assert "Code Intelligence (agent composite)" in report
    # documentaire mean llm_call_count = 1.0
    assert "1.0 / 1.0 / 1" in report
    # code_intelligence: 1/2 traces hit the hop cap
    assert "1/2 (50%)" in report


def test_j48_report_handles_empty_log_gracefully(tmp_path):
    """J48: before any real traffic has been recorded, the report must not
    crash or fabricate numbers -- it should say so plainly."""
    import sys
    from pathlib import Path

    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from report_llm_call_budget import build_budget_report

    log_file = tmp_path / "empty_reasoning_trace.jsonl"
    report = build_budget_report(log_filepath=log_file)
    assert "Aucune trace enregistree" in report
