"""Helper utilities for the ORM agent node."""

import logging
from typing import Any, List, Literal, Tuple

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from config import settings
from core.llm.llm_client import get_chat_llm, invoke_llm

logger = logging.getLogger(__name__)


class QueryPlan(BaseModel):
    """Business constraints extracted before technical ORM fields are selected."""

    model_config = ConfigDict(strict=True, extra="forbid")
    subject: str = Field(min_length=1)
    conditions: list[str] = Field(default_factory=list)
    result_kind: Literal["count", "list", "aggregate", "top", "detail", "unknown"]
    ambiguity: str | None = None
    answer_language: str = Field(min_length=1)


MEASURE_TOOLS = frozenset({"read_group", "search_read", "read"})


def format_query_plan(plan: QueryPlan) -> str:
    return (
        "Plan métier obligatoire (à vérifier avec fields_get avant toute lecture) :\n"
        f"- Sujet : {plan.subject}\n"
        f"- Conditions : {', '.join(plan.conditions) or 'aucune'}\n"
        f"- Résultat : {plan.result_kind}\n"
        f"- Ambiguïté : {plan.ambiguity or 'aucune'}\n"
        f"- Langue de la réponse : {plan.answer_language}, libellés Odoo non traduits\n"
        "Chaque condition doit apparaître dans le filtre ou le regroupement final."
    )


def counted_instead_of_measured(plan: QueryPlan | None, tool_names: list[str]) -> bool:
    """True when a sum, total or average was asked and only rows were counted."""
    used = set(tool_names)
    return bool(plan) and plan.result_kind == "aggregate" and "search_count" in used and not used & MEASURE_TOOLS


def _build_llm(**kwargs):
    reasoning_effort = kwargs.pop("reasoning_effort", settings.ERP_REASONING_EFFORT)
    return get_chat_llm(reasoning_effort=reasoning_effort, **kwargs)


def resolve_orm_tools() -> List[Any]:
    """Expose only model-agnostic, read-only ORM primitives."""
    from erp_data.runtime.langchain_tools import TYPED_ORM_LANGCHAIN_TOOLS

    return list(TYPED_ORM_LANGCHAIN_TOOLS)


def plan_orm_question(question: str, llm_builder=None) -> tuple[QueryPlan | None, int]:
    """Extract business constraints without inventing instance-specific ORM names."""
    try:
        llm = (llm_builder or _build_llm)(
            temperature=0.0, max_tokens=256, reasoning_effort="none"
        )
        planner = llm.with_structured_output(QueryPlan, method="json_schema")
    except AttributeError:
        return None, 0
    try:
        messages = [
            SystemMessage(content=(
                "Planifie une question de données Odoo avant toute lecture. Ne réponds pas à la question. "
                "Extrais le sujet métier, chaque condition obligatoire et le type de résultat demandé : "
                "count = nombre d'enregistrements ; aggregate = somme, total ou moyenne d'une valeur numérique ; "
                "list = liste ; top = classement ; detail = fiche d'un enregistrement. "
                "Les conditions restent exprimées en langage métier : n'invente aucun nom technique de modèle, "
                "champ ou valeur. Un mot qui précise le type d'objet, l'état, l'activité ou la période doit rester "
                "une condition distincte. Si une condition est ambiguë, signale-la dans ambiguity. "
                "answer_language : nom de la langue dans laquelle la question est écrite."
            )),
            HumanMessage(content=question),
        ]
        result = invoke_llm(planner, messages)
        return (result if isinstance(result, QueryPlan) else QueryPlan.model_validate(result)), 1
    except Exception as exc:
        logger.warning("ORM query planning unavailable: %s", type(exc).__name__)
        return None, 1


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


def _single_answer(prompt: str) -> str:
    response = invoke_llm(
        _build_llm(temperature=0.0, max_tokens=settings.ORM_SYNTHESIS_MAX_TOKENS), [HumanMessage(content=prompt)]
    )
    return response.content


def force_final_synthesis(question: str, tool_observations: List[str]) -> Tuple[str, int]:
    """Synthesize final answer when the ReAct iteration budget is exhausted."""
    logger.warning("Node [orm_agent_loop]: Recursion limit reached. Forcing final answer.")
    from erp_data.prompts import build_orm_synthesis_prompt

    try:
        return _single_answer(build_orm_synthesis_prompt(question, tool_observations)), 1
    except Exception as exc:
        logger.error("Forced synthesis failed: %s", exc)
        return "Je n'ai pas pu obtenir de réponse complète à partir des observations disponibles.", 1


def explain_refusals(question: str, tool_observations: List[str]) -> Tuple[str, int]:
    """Explain in plain words why no read succeeded; empty text when the explanation call fails."""
    from erp_data.prompts import build_orm_refusal_prompt

    try:
        return _single_answer(build_orm_refusal_prompt(question, tool_observations)).strip(), 1
    except Exception as exc:
        logger.error("Refusal explanation failed: %s", exc)
        return "", 1
