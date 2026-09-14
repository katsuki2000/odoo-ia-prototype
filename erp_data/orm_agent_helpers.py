"""Helper utilities for ORM ReAct agent node."""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import HumanMessage

from config.settings import GROQ_MODEL
from core.llm.llm_client import invoke_with_rate_limit, _current_groq_key, get_chat_llm

logger = logging.getLogger(__name__)

# Backward-compatible aliases
_build_groq_llm = get_chat_llm


def _get_chat_groq():
    import sys
    g = sys.modules.get("core.graph.graph")
    if g and hasattr(g, "ChatGroq"):
        return g.ChatGroq
    from langchain_groq import ChatGroq
    return ChatGroq


def resolve_orm_tools(skills: Dict[str, Any]) -> List[Any]:
    """Return enabled ORM tools based on active skills."""
    from erp_data.tools.crm import search_partner, get_recent_tickets
    from erp_data.tools.sales import (
        get_total_sales,
        get_average_sales,
        get_sale_details,
        get_order_count,
        get_top_selling_products,
    )
    from erp_data.tools.inventory import (
        get_order_status,
        get_product_stock,
        list_out_of_stock_products,
    )
    from erp_data.tools.accounting import get_period_revenue, get_total_invoices

    all_tools = [search_partner]
    if skills.get("ventes", True):
        all_tools.extend([
            get_total_sales, get_order_status, get_period_revenue,
            get_average_sales, get_sale_details, get_order_count,
            get_top_selling_products,
        ])
    if skills.get("stocks", True):
        all_tools.extend([get_product_stock, list_out_of_stock_products])
    if skills.get("comptabilite", True):
        all_tools.extend([get_total_invoices])
    if skills.get("tickets", True):
        all_tools.extend([get_recent_tickets])
    return all_tools


def recover_malformed_tool_call(
    err_str: str, all_tools: List[Any]
) -> Optional[Tuple[str, dict, Any]]:
    """Attempt to parse function call from Groq failed_generation error message."""
    if "failed_generation" not in err_str:
        return None
    match = re.search(r'<function=(\w+)>\s*(\{.*?\})', err_str)
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
    if tool_name not in [t.name for t in all_tools]:
        return tool_name, tool_args, f"Outil '{tool_name}' non disponible."

    try:
        tool_map = {t.name: t for t in all_tools}
        observation = tool_map[tool_name].invoke(tool_args)
    except Exception as e:
        err_str = str(e)
        logger.error("Tool call error for %s: %s", tool_name, e)
        if "Access Denied" in err_str or "AccessDenied" in err_str:
            observation = (
                f"Vous n'avez pas les droits d'acces necessaires pour "
                f"consulter ces donnees ({tool_name}). Contactez votre "
                f"administrateur pour obtenir les permissions requises."
            )
        else:
            observation = (
                f"L'outil {tool_name} n'a pas pu s'executer correctement. "
                f"Veuillez reessayer ou reformuler votre question."
            )
    return tool_name, tool_args, observation


def force_final_synthesis(question: str, tool_observations: List[str]) -> Tuple[str, int]:
    """Synthesize final answer when ReAct iteration limit is reached."""
    logger.warning("Node [orm_agent_loop]: Recursion limit reached. Forcing final answer.")
    from erp_data.prompts import build_orm_synthesis_prompt
    synthesis_prompt = build_orm_synthesis_prompt(question, tool_observations)
    llm_calls = 0
    try:
        synth_box = [_build_groq_llm(temperature=0.0, max_retries=0, max_tokens=512)]

        def _rebuild():
            synth_box[0] = _build_groq_llm(temperature=0.0, max_retries=0, max_tokens=512)
            return synth_box[0]

        final_resp, _ = invoke_with_rate_limit(
            synth_box[0], [HumanMessage(content=synthesis_prompt)],
            rebuild_llm=_rebuild,
        )
        llm_calls += 1
        return final_resp.content, llm_calls
    except Exception as e:
        llm_calls += 1
        logger.error("Forced synthesis failed: %s", e)
        return "Je n'ai pas pu obtenir une réponse complète. Veuillez reformuler la question.", llm_calls
