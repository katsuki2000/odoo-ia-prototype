"""Rate limiting headers, error recovery, and context reduction helpers for LLM client."""

import logging
import re
from typing import Any, List, Optional
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

logger = logging.getLogger(__name__)

_TOOL_MSG_HARD_CAP = 400
_TOOL_USE_FAILED_RE = re.compile(
    r"'code':\s*'tool_use_failed'.*?'failed_generation':\s*'(.*?)'\s*\}",
    re.DOTALL,
)
_FAILED_GEN_CALL_RE = re.compile(r"<function=(\w+)>(\{.*\})")


class ToolCallFallback:
    """Minimal stand-in for AIMessage when recovering tool_calls."""
    def __init__(self, tool_calls: List[dict]):
        self.tool_calls = tool_calls
        self.content = ""


def parse_reset_seconds(header_value: str, default: float = 20.0) -> float:
    """Parse rate-limit reset duration from header strings."""
    if not header_value:
        return default
    match = re.match(r"(?:(\d+)m)?([\d.]+)s", header_value.strip())
    if not match:
        return default
    minutes = float(match.group(1)) if match.group(1) else 0.0
    seconds = float(match.group(2))
    return minutes * 60 + seconds


def extract_rate_limit_headers(exc: Exception) -> dict:
    """Extract HTTP response headers from rate limit exceptions."""
    for attr_path in ("response", "http_response", "resp"):
        resp = getattr(exc, attr_path, None)
        if resp is not None and hasattr(resp, "headers"):
            return dict(resp.headers)
    cause = getattr(exc, "__cause__", None)
    if cause is not None:
        resp = getattr(cause, "response", None)
        if resp is not None and hasattr(resp, "headers"):
            return dict(resp.headers)
    return {}


def try_recover_tool_use_failed(exc: Exception) -> Optional[ToolCallFallback]:
    """Recover malformed tool call from tool_use_failed exception."""
    msg = str(exc)
    if "tool_use_failed" not in msg:
        return None
    match = _TOOL_USE_FAILED_RE.search(msg)
    if not match:
        return None
    call_match = _FAILED_GEN_CALL_RE.search(match.group(1))
    if not call_match:
        return None
    fn_name, args_raw = call_match.group(1), call_match.group(2)
    try:
        import json
        args = json.loads(args_raw)
    except Exception:
        return None
    logger.warning("Recovered malformed tool call via failed_generation: %s(%s)", fn_name, args)
    return ToolCallFallback([{
        "name": fn_name, "args": args, "id": f"fallback_{fn_name}", "type": "tool_call",
    }])


def reduce_message_context(messages: list) -> list:
    """Truncate excessively long messages to stay within payload limits."""
    reduced = []
    for msg in messages:
        if (
            isinstance(msg, ToolMessage)
            and isinstance(msg.content, str)
            and len(msg.content) > _TOOL_MSG_HARD_CAP
        ):
            reduced.append(
                ToolMessage(
                    content=(
                        msg.content[:_TOOL_MSG_HARD_CAP]
                        + "\n[... tronqué pour respecter la limite de taille de requête ...]"
                    ),
                    tool_call_id=msg.tool_call_id,
                )
            )
        elif (
            isinstance(msg, SystemMessage)
            and isinstance(msg.content, str)
            and len(msg.content) > 1000
        ):
            reduced.append(
                SystemMessage(
                    content=(
                        msg.content[:1000]
                        + "\n[... tronqué pour respecter la limite de taille ...]"
                    )
                )
            )
        elif (
            isinstance(msg, HumanMessage)
            and isinstance(msg.content, str)
            and len(msg.content) > 1500
        ):
            reduced.append(
                HumanMessage(
                    content=(
                        msg.content[:1500]
                        + "\n[... tronqué pour respecter la limite de taille de requête ...]"
                    )
                )
            )
        else:
            reduced.append(msg)
    return reduced
