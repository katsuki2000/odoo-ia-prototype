"""
core/graph_compat.py

Backward-compatible re-exports for legacy tests and external callers that
historically imported schemas, guards, helpers, and agents from core.graph.graph.
"""

from core.schemas import (
    AssistantResponse,
    SourceReference,
    LLMResponse,
    QueryRoute,
    source_display_title,
)

from core.llm.llm_client import (
    get_chat_llm,
    invoke_with_rate_limit as _invoke_with_rate_limit,
    _parse_reset_seconds,
    _extract_rate_limit_headers,
    _ToolCallFallback,
    _try_recover_tool_use_failed,
    _reduce_message_context,
    _TOOL_MSG_HARD_CAP,
    _TOOL_USE_FAILED_RE,
    _FAILED_GEN_CALL_RE,
    _llm_call_lock,
    _last_llm_call_time,
    MIN_LLM_CALL_INTERVAL,
)

from core.output import (
    _DEGENERATE_REPETITION_RE,
    _DEGENERATE_LINE_REPETITION_MIN_REPEATS,
    _DEGENERATE_LINE_MIN_LENGTH,
    _DEGENERATE_BLANK_RUN_RE,
    _DEGENERATE_PREFIX_LENGTH,
    _DEGENERATE_PREFIX_MIN_REPEATS,
    _detect_degenerate_repetition,
    _strip_degenerate_repetition,
    _detect_degenerate_line_repetition,
    _strip_degenerate_line_repetition,
    _detect_degenerate_blank_run,
    _strip_degenerate_blank_run,
    _detect_degenerate_growing_repetition,
    _strip_degenerate_growing_repetition,
    _detect_any_degenerate_repetition,
    _strip_any_degenerate_repetition,
)

from core.state import RAGState
from core.routing.routing import (
    route,
    route_decision,
)

from document_rag.generate_node import (
    _parse_raw_json_answer,
    generate,
)


from erp_data.orm_agent_node import orm_agent_loop

__all__ = [k for k in globals().keys() if not k.startswith("__")]
