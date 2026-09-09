"""
code_intelligence/business_resolver_arbitration.py

Bounded LLM candidate arbitration over ambiguous or low-confidence fuzzy matches.
"""

import logging
from typing import List, Optional

_logger = logging.getLogger(__name__)

AMBIGUITY_GAP_THRESHOLD = 10.0
WIDENED_CANDIDATE_THRESHOLD = 30
WIDENED_CANDIDATE_LIMIT = 8

from .prompts import _ARBITRATION_SYSTEM_PROMPT, _build_arbitration_prompt


def _llm_arbitrate(query_text: str, candidates: List[str], llm) -> Optional[str]:
    """Bounded LLM candidate selection over a closed list."""
    if llm is None:
        _logger.warning("LLM arbitration requested but no llm client was provided; skipping.")
        return None

    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        from core.llm_client import get_chat_llm, invoke_with_rate_limit

        prompt = _build_arbitration_prompt(query_text, candidates)
        messages = [
            SystemMessage(content=_ARBITRATION_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        def _rebuild_arbitration_llm():
            return get_chat_llm(temperature=0.0, max_retries=0)

        response, _wait = invoke_with_rate_limit(
            llm, messages, rebuild_llm=_rebuild_arbitration_llm,
        )
        raw = (response.content or "").strip()
    except Exception:
        _logger.exception("LLM arbitration call failed for query=%r candidates=%r", query_text, candidates)
        return None

    if raw == "NONE":
        return None
    if raw in candidates:
        return raw

    _logger.warning("LLM arbitration returned an out-of-list value: %r (candidates=%r)", raw, candidates)
    return None
