"""Helper utilities for the ORM agent node."""

import logging
from typing import Any, List, Tuple

from langchain_core.messages import HumanMessage

from config import settings
from core.llm.llm_client import get_chat_llm, invoke_llm

logger = logging.getLogger(__name__)

def _build_llm(**kwargs):
    return get_chat_llm(reasoning_effort=settings.ERP_REASONING_EFFORT, **kwargs)


def resolve_orm_tools() -> List[Any]:
    """Expose only model-agnostic, read-only ORM primitives."""
    from erp_data.runtime.langchain_tools import TYPED_ORM_LANGCHAIN_TOOLS

    return list(TYPED_ORM_LANGCHAIN_TOOLS)


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
    llm_calls = 1
    try:
        final_resp = invoke_llm(
            _build_llm(temperature=0.0, max_tokens=512), [HumanMessage(content=synthesis_prompt)])
        return final_resp.content, llm_calls
    except Exception as exc:
        logger.error("Forced synthesis failed: %s", exc)
        return (
            "Je n'ai pas pu obtenir de réponse complète à partir des observations disponibles.",
            llm_calls,
        )
