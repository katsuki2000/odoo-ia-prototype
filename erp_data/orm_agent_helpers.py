"""Helper utilities for the ORM agent node."""

import logging
import re
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
DOMAIN_QUERY_TOOLS = frozenset({"search", "search_read", "search_count", "read_group", "name_search"})


def format_query_plan(plan: QueryPlan) -> str:
    conditions = "\n".join(
        f"[{condition_id}] {condition}"
        for condition_id, condition in enumerate(plan.conditions, start=1)
    ) or "aucune"
    return (
        "Plan métier obligatoire (à vérifier avec fields_get avant toute lecture) :\n"
        f"- Sujet obligatoire [0] : {plan.subject}\n"
        f"- Conditions obligatoires :\n{conditions}\n"
        f"- Résultat : {plan.result_kind}\n"
        f"- Ambiguïté : {plan.ambiguity or 'aucune'}\n"
        f"- Langue de la réponse : {plan.answer_language}, libellés Odoo non traduits\n"
        "condition_filters doit couvrir le sujet [0] et chaque condition numérotée. Le fragment [0] peut être vide "
        "si le modèle sélectionné porte un sujet simple ; pour un sujet composé, il doit être non vide. Les fragments "
        "[1..n] doivent être non vides. Le domaine "
        "exécuté doit être exactement la concaténation des fragments non vides, dans l'ordre des identifiants."
    )


def validate_condition_filters(plan: QueryPlan | None, tool_name: str, arguments: dict) -> tuple[bool, str | None]:
    if plan is None or tool_name not in DOMAIN_QUERY_TOOLS:
        return False, None

    domain = arguments.get("domain") or []
    bindings = arguments.get("condition_filters") or []
    if not isinstance(domain, list) or not isinstance(bindings, list):
        return False, "Query refused: domain and condition_filters must be lists."

    expected_ids = set(range(len(plan.conditions) + 1))
    if expected_ids and not bindings:
        return False, "Query refused: map the required plan conditions to condition_filters before reading data."
    bound_ids = set()
    bound_domain = []
    for binding in bindings:
        if not isinstance(binding, dict):
            return False, "Query refused: each condition filter must identify a condition and its domain fragment."
        condition_id = binding.get("condition_id")
        fragment = binding.get("domain")
        if isinstance(condition_id, bool) or not isinstance(condition_id, int):
            return False, "Query refused: condition_id must be an integer from the query plan."
        if condition_id not in expected_ids:
            return False, f"Query refused: condition_id {condition_id} is not in the query plan."
        if condition_id in bound_ids:
            return False, f"Query refused: condition_id {condition_id} is bound more than once."
        if not isinstance(fragment, list):
            return False, f"Query refused: condition {condition_id} needs a non-empty domain fragment."
        if condition_id != 0 and not fragment:
            return False, f"Query refused: condition {condition_id} needs a non-empty domain fragment."
        if condition_id == 0 and not fragment and _subject_requires_domain_filter(plan):
            return False, "Query refused: a compound subject needs a non-empty domain fragment."
        bound_ids.add(condition_id)
        bound_domain.extend(_normalize_domain_fragment(fragment))

    missing_ids = sorted(expected_ids - bound_ids)
    if missing_ids:
        return False, (
            "Query refused: condition_filters must cover every plan condition; "
            f"missing condition_id values: {missing_ids}."
        )
    if _normalize_domain(bound_domain) != _normalize_domain(domain):
        return False, "Query refused: domain must exactly match its condition_filters fragments."
    return True, None


def _normalize_domain(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return [_normalize_domain(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_domain(item) for key, item in value.items()}
    return value


def _normalize_domain_fragment(fragment: list) -> list:
    if len(fragment) == 3 and isinstance(fragment[0], str) and isinstance(fragment[1], str):
        return [fragment]
    return fragment


def _materialize_condition_domain(arguments: dict) -> dict:
    if arguments.get("domain"):
        return arguments
    bindings = arguments.get("condition_filters") or []
    fragments = []
    for binding in bindings:
        if not isinstance(binding, dict) or not isinstance(binding.get("domain"), list):
            return arguments
        fragments.extend(_normalize_domain_fragment(binding["domain"]))
    if not fragments:
        return arguments
    return {**arguments, "domain": fragments}


def successful_tool_observation(observation: Any) -> bool:
    text = str(observation)
    return not text.startswith((
        "ORM read refused:",
        "ORM operation '",
        "Query refused:",
        "Tool '",
    ))


def is_query_contract_refusal(observation: Any) -> bool:
    """Return whether the local query contract rejected the tool call before Odoo."""
    return str(observation).startswith("Query refused:")


def counted_instead_of_measured(plan: QueryPlan | None, tool_names: list[str]) -> bool:
    """True when a sum, total or average was asked and only rows were counted."""
    used = set(tool_names)
    return bool(plan) and plan.result_kind == "aggregate" and "search_count" in used and not used & MEASURE_TOOLS


def _build_llm(**kwargs):
    reasoning_effort = kwargs.pop("reasoning_effort", settings.ERP_REASONING_EFFORT)
    return get_chat_llm(reasoning_effort=reasoning_effort, **kwargs)


def _normalize_business_phrase(value: str) -> str:
    """Compare business phrases without making language- or model-specific guesses."""
    return " ".join(re.findall(r"\w+", value.casefold(), flags=re.UNICODE))


def _subject_requires_domain_filter(plan: QueryPlan) -> bool:
    """Require a domain fragment when the subject carries multiple business terms."""
    return len(_normalize_business_phrase(plan.subject).split()) >= 2


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
                "Le sujet décrit uniquement le type d'objet ; transfère son état, son type métier, sa partie "
                "prenante et toute autre précision dans les conditions. Les conditions restent exprimées en langage "
                "métier : n'invente aucun nom technique de modèle, champ ou valeur. Chaque qualificatif est une "
                "condition distincte, sauf lorsqu'une expression explique la définition de la précédente : combine "
                "alors ces reformulations équivalentes en une seule condition. Le sujet doit aussi être mappé par un "
                "filtre de domaine propre, même si le modèle semble le représenter. Numérote les conditions dans "
                "leur ordre d'apparition. Si le sujet est une expression composée (par exemple « factures clients », "
                "« commandes fournisseurs » ou « écritures comptables »), garde l'expression complète comme première "
                "condition obligatoire et utilise comme sujet le type d'objet non qualifié ; ne laisse aucun qualificatif "
                "dans le seul sujet. "
                "Si une condition est ambiguë, signale-la dans ambiguity. "
                "answer_language : nom de la langue dans laquelle la question est écrite."
            )),
            HumanMessage(content=question),
        ]
        result = invoke_llm(planner, messages)
        plan = result if isinstance(result, QueryPlan) else QueryPlan.model_validate(result)
        return plan, 1
    except Exception as exc:
        logger.warning("ORM query planning unavailable: %s", type(exc).__name__)
        return None, 1


def execute_tool_call(
    tool_call: dict, all_tools: List[Any], plan: QueryPlan | None = None,
) -> Tuple[str, dict, Any, bool]:
    """Execute a single tool call with graceful error handling."""
    tool_name = tool_call["name"]
    tool_args = tool_call["args"]
    tool_map = {tool.name: tool for tool in all_tools}
    if tool_name not in tool_map:
        return tool_name, tool_args, f"Tool '{tool_name}' is not available.", False
    tool = tool_map[tool_name]
    try:
        tool_args = tool.args_schema.model_validate(tool_args).model_dump(exclude_none=True)
    except Exception as exc:
        logger.error("Tool argument validation failed for %s: %s", tool_name, exc)
        return tool_name, tool_args, f"Query refused: invalid arguments for {tool_name}.", False
    tool_args = _materialize_condition_domain(tool_args)
    coverage_complete, coverage_error = validate_condition_filters(plan, tool_name, tool_args)
    if coverage_error:
        return tool_name, tool_args, coverage_error, False

    try:
        observation = tool.invoke(tool_args)
    except Exception as exc:
        logger.error("Tool call error for %s: %s", tool_name, exc)
        observation = (
            f"ORM operation '{tool_name}' failed or was refused. "
            "Check the requested model, fields, filters, and the requester's Odoo permissions."
        )
    return tool_name, tool_args, observation, coverage_complete


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
