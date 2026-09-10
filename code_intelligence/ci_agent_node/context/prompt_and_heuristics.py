"""
code_intelligence/ci_prompt_and_heuristics.py

System prompt, hop limits, tool call deduplication, and observation truncation helpers.
"""

import logging
from typing import Optional, Tuple, Dict, Any

logger = logging.getLogger(__name__)

from code_intelligence.answer_text_signals import _TRUNCATION_MARKER, _match_near_truncation


# Maximum hops allowed per question.
CI_MAX_HOPS = 4

# Composite tools whose dedup key is only (tool_name, model_name).
_MODEL_KEYED_TOOLS = frozenset({
    "analyze_security_locks",
    "analyze_server_actions",
    "who_has_access_to",
    "evaluate_record_rules",
    "describe_workflow",
    "trace_full_inheritance",
    "list_involved_modules",
    "analyze_data_constraints",
})


def _tool_call_key(tool_name: str, tool_args: "Dict[str, Any]") -> "Optional[Tuple]":
    """Single source of truth for the seen_calls dedup key."""
    model_name = tool_args.get("model_name")
    if not model_name:
        return None
    if tool_name == "analyze_method_override_chain":
        method_name = tool_args.get("method_name")
        return (tool_name, model_name, method_name) if method_name else None
    if tool_name == "button_execution_path":
        btn = tool_args.get("button_name") or tool_args.get("button_identifier")
        return (tool_name, model_name, btn) if btn else None
    if tool_name in _MODEL_KEYED_TOOLS:
        return (tool_name, model_name)
    return None


def _truncate_observation(text: str, limit: int) -> str:
    """Truncate text to at most limit characters without cutting inside a token."""
    if len(text) <= limit:
        return text

    cut = text[:limit]
    newline = cut.rfind("\n")
    if newline > 0:
        cut = cut[:newline]
    else:
        space = cut.rfind(" ")
        if space > 0:
            cut = cut[:space]

    return cut + _TRUNCATION_MARKER
