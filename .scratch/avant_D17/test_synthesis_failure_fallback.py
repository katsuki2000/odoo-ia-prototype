from unittest.mock import MagicMock

from code_intelligence.agent.loop import SYNTHESIS_UNAVAILABLE_ANSWER, run_react_loop


def test_synthesis_failure_never_returns_raw_tool_observations(monkeypatch):
    ctx = MagicMock()
    ctx.tool_observations = ["RAW LOCK ANALYSIS custom.purchase.request"]
    ctx.hop_budget_exhausted = True
    ctx.security_distinction_reminder_sent = True
    ctx.question = "comment faire une demande d'achat?"
    monkeypatch.setattr(
        "code_intelligence.agent.loop._build_dynamic_uncertainty_answer", lambda _raw: None,
    )

    def failing_invoke(*_args, **_kwargs):
        raise RuntimeError("model not found")

    monkeypatch.setattr("code_intelligence.agent.loop._invoke_with_rate_limit", failing_invoke)
    llm = MagicMock()
    answer = run_react_loop(ctx, "system", [], 1, [llm], lambda: llm)
    assert answer == SYNTHESIS_UNAVAILABLE_ANSWER
    assert "RAW LOCK ANALYSIS" not in answer
