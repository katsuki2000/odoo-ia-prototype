"""Helper utilities for the ORM agent node."""

import json
import logging
import re
from typing import Any, List, Optional, Tuple

from langchain_core.messages import HumanMessage

from core.llm.llm_client import invoke_with_rate_limit, get_chat_llm

logger = logging.getLogger(__name__)

_build_llm = get_chat_llm


def resolve_orm_tools(_skills: Optional[dict[str, Any]] = None) -> List[Any]:
    """Expose only model-agnostic, read-only ORM primitives."""
    from erp_data.runtime.langchain_tools import TYPED_ORM_LANGCHAIN_TOOLS

    return list(TYPED_ORM_LANGCHAIN_TOOLS)


def recover_malformed_tool_call(
    err_str: str, all_tools: List[Any]
) -> Optional[Tuple[str, dict, Any]]:
    """Recover a tool call from a provider error when its payload is recognizable."""
    if "failed_generation" not in err_str:
        return None
    match = re.search(r"<function=(\w+)>\s*(\{.*?\})", err_str)
    if not match:
        return None
    fn_name = match.group(1)
    try:
        fn_args = json.loads(match.group(2))
        tool_map = {t.name: t for t in all_tools}
        if fn_name in tool_map:
            logger.info("Recovered malformed tool call: %s(%s)", fn_name, fn_args)
            observation = tool_map[fn_name].invoke(fn_args)
            return fn_name, fn_args, observation
    except Exception as parse_err:
        logger.error("Recovery parse failed: %s", parse_err)
    return None


def execute_tool_call(
    tool_call: dict, all_tools: List[Any]
) -> Tuple[str, dict, Any]:
    """Execute a single tool call with graceful error handling."""
    tool_name = tool_call["name"]
    tool_args = tool_call["args"]
    tool_map = {tool.name: tool for tool in all_tools}
    if tool_name not in tool_map:
        return tool_name, tool_args, f"Tool '{tool_name}' is not available."

    try:
        observation = tool_map[tool_name].invoke(tool_args)
    except Exception as exc:
        logger.error("Tool call error for %s: %s", tool_name, exc)
        observation = (
            f"ORM operation '{tool_name}' failed or was refused. "
            "Check the requested model, fields, filters, and the requester's Odoo permissions."
        )
    return tool_name, tool_args, observation


def force_final_synthesis(question: str, tool_observations: List[str]) -> Tuple[str, int]:
    """Synthesize final answer when the ReAct iteration budget is exhausted."""
    logger.warning("Node [orm_agent_loop]: Recursion limit reached. Forcing final answer.")
    from erp_data.prompts import build_orm_synthesis_prompt

    synthesis_prompt = build_orm_synthesis_prompt(question, tool_observations)
    llm_calls = 0
    try:
        synth_box = [_build_llm(temperature=0.0, max_retries=0, max_tokens=512)]

        def _rebuild():
            synth_box[0] = _build_llm(temperature=0.0, max_retries=0, max_tokens=512)
            return synth_box[0]

        final_resp, _ = invoke_with_rate_limit(
            synth_box[0],
            [HumanMessage(content=synthesis_prompt)],
            rebuild_llm=_rebuild,
        )
        llm_calls += 1
        return final_resp.content, llm_calls
    except Exception as exc:
        llm_calls += 1
        logger.error("Forced synthesis failed: %s", exc)
        return (
            "Je n'ai pas pu obtenir une réponse complète à partir des observations disponibles.",
            llm_calls,
        )
