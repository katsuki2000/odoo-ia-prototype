"""LLM-based interpretation layer for method override static analysis findings."""

import json
import logging
from typing import List, Optional

_logger = logging.getLogger(__name__)

_LLM_CONFIDENCE_CLOSED_SET = {"high", "medium", "low"}

from .prompts import build_override_interpretation_messages


def interpret_override_chain_with_llm(
    model_name: str,
    method_name: str,
    warnings: List[str],
    snippets: List[str],
    llm,
) -> Optional[dict]:
    if not warnings or llm is None:
        return None

    try:
        messages = build_override_interpretation_messages(
            model_name, method_name, warnings, snippets
        )
        response = llm.invoke(messages)
        raw = (response.content or "").strip()
    except Exception as e:
        _logger.warning(
            "LLM interpretation call failed for %s.%s: %s", model_name, method_name, e
        )
        return None

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        _logger.warning(
            "LLM interpretation returned non-JSON response for %s.%s: %r",
            model_name, method_name, raw,
        )
        return None

    if not isinstance(parsed, dict):
        return None

    summary = parsed.get("summary")
    confidence = parsed.get("confidence")

    if confidence not in _LLM_CONFIDENCE_CLOSED_SET:
        _logger.warning(
            "LLM interpretation returned out-of-set confidence for %s.%s: %r",
            model_name, method_name, confidence,
        )
        return None

    if not summary or not isinstance(summary, str):
        return None

    return {"summary": summary, "confidence": confidence}
