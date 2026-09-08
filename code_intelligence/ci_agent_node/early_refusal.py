"""
code_intelligence/ci_agent_node/early_refusal.py

Shared builder for the 3 early-refusal paths of the CI agent (out-of-scope,
prompt injection, massive extraction) -- these were 3 duplicated blocks in
the former ci_agent_node.py monolith, unified here (refactor, see
todo/contexte.txt). Behavior unchanged.
"""

import time

from core.schemas import AssistantResponse


def build_early_refusal_response(
    answer: str, trace_logger, trace_id: str, question: str,
    start_time: float, state: dict, hop_cap: int,
) -> dict:
    response = AssistantResponse(answer=answer, sources=[], confidence=0.0)
    timing = state.get("timing", {}).copy()
    timing["code_intelligence_time"] = time.time() - start_time
    trace_logger.log_summary(
        trace_id=trace_id, branch="code_intelligence", question=question,
        hop_count=0, llm_call_count=0,
        total_time_ms=timing["code_intelligence_time"] * 1000,
        hop_cap=hop_cap,
    )
    return {"response": response, "raw_answer": response.answer, "timing": timing}
