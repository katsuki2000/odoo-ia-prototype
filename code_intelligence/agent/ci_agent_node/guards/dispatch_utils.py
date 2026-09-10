"""
code_intelligence/ci_dispatch_utils.py

Dispatch helpers, model ranking, user group overrides, noise reduction,
and dynamic uncertainty / out-of-scope answer formatters.
"""

import json
import logging
import re
from typing import Optional, List

from code_intelligence.agent.ci_agent_node.context.context_extractors import _AUTOMATION_PATTERN

logger = logging.getLogger(__name__)


def _question_suggests_automation_bypass(question: str) -> bool:
    return bool(_AUTOMATION_PATTERN.search(question))


def _rank_and_cap_resolved_models(question: str, resolved_models: List[str], max_models: int) -> List[str]:
    """Rank resolved model technical names by lexical relevance to question."""
    if len(resolved_models) <= max_models:
        return resolved_models
    from rapidfuzz import fuzz
    question_lower = question.lower()

    _BILINGUAL_EXPANSIONS = {
        "rule": "regle règle",
        "log": "journal logs audit",
        "wizard": "assistant",
        "user": "utilisateur",
        "partner": "partenaire contact",
        "company": "societe société entreprise",
        "move": "mouvement",
        "quant": "quantite quantité stock",
        "line": "ligne",
    }

    def _model_text(m_name: str) -> str:
        parts = m_name.replace(".", " ").replace("_", " ").lower().split()
        expanded_parts = list(parts)
        for p in parts:
            if p in _BILINGUAL_EXPANSIONS:
                expanded_parts.append(_BILINGUAL_EXPANSIONS[p])
        return " ".join(expanded_parts)

    scored = [
        (name, fuzz.token_set_ratio(question_lower, _model_text(name)))
        for name in resolved_models
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    kept = [name for name, _score in scored[:max_models]]
    logger.warning(
        "Node [code_intelligence_agent]: Truncating resolved models from %d to "
        "MAX_MODELS_PER_QUERY (%d), ranked by relevance -- kept: %s.",
        len(resolved_models), max_models, kept,
    )
    return kept


def _override_user_groups_arg(tool_name: str, tool_args: dict, resolved_user_group_xmlids: list) -> dict:
    """Overrides LLM-guessed user_groups_json with requester's real group XML-IDs."""
    if tool_name not in ("evaluate_record_rules", "button_execution_path"):
        return tool_args

    real_groups_json = json.dumps(resolved_user_group_xmlids)
    llm_proposed = tool_args.get("user_groups_json")
    if llm_proposed and llm_proposed != real_groups_json:
        logger.warning(
            "Node [code_intelligence_agent]: overriding LLM-guessed "
            "user_groups_json (%s) with the real requester groups (%s).",
            llm_proposed, real_groups_json,
        )
    tool_args["user_groups_json"] = real_groups_json
    return tool_args


_COULD_NOT_RESOLVE_RE = re.compile(
    r"""Group identifier ['"].*?['"] could not be resolved""",
    re.IGNORECASE,
)


def _strip_group_resolution_noise(
    tool_observations: List[str],
    resolved_user_group_xmlids: list,
    tool_observation_models: List[str],
    tool_observation_tools: Optional[List[str]] = None,
):
    """Remove who_has_access_to 'could not be resolved' observations when real groups evaluated."""
    if not resolved_user_group_xmlids:
        if tool_observation_tools is None:
            return tool_observations, tool_observation_models
        return tool_observations, tool_observation_models, tool_observation_tools

    has_deterministic_fact = any(
        "[FAIT DÉTERMINISTIQUE]" in obs for obs in tool_observations
    )
    if not has_deterministic_fact:
        if tool_observation_tools is None:
            return tool_observations, tool_observation_models
        return tool_observations, tool_observation_models, tool_observation_tools

    cleaned = []
    cleaned_models = []
    cleaned_tools = [] if tool_observation_tools is not None else None
    _tools_iter = tool_observation_tools if tool_observation_tools is not None else [None] * len(tool_observations)
    for obs, model, tname in zip(tool_observations, tool_observation_models, _tools_iter):
        if _COULD_NOT_RESOLVE_RE.search(obs):
            logger.info(
                "Node [code_intelligence_agent]: stripping 'could not be "
                "resolved' observation from synthesis context: %.120s",
                obs,
            )
            continue
        cleaned.append(obs)
        cleaned_models.append(model)
        if cleaned_tools is not None:
            cleaned_tools.append(tname)
    if tool_observation_tools is None:
        return cleaned, cleaned_models
    return cleaned, cleaned_models, cleaned_tools


def _extract_first_scoped_file_link(text: str) -> str:
    match = re.search(r"\[[^\]]+\]\(file:///[^\)]+#L\d+-L\d+\)", text)
    return match.group(0) if match else ""


_TECHNICAL_MODEL_LOOKALIKE_RE = re.compile(r"\b[a-z][a-z_]*(?:\.[a-z][a-z_]*){1,3}\b")


def _force_out_of_scope_model_answer(question: str, concept) -> Optional[str]:
    """Force an honest decline if concept unresolved AND question names unindexed technical model."""
    if concept.is_resolved:
        return None
    match = _TECHNICAL_MODEL_LOOKALIKE_RE.search(question.lower())
    if not match:
        return None
    model_name = match.group(0)
    return (
        f"Le modele '{model_name}' n'est pas present dans le corpus indexe par cet outil "
        f"(ni personnalise par un module custom_*, ni charge par un autre mecanisme connu de "
        f"cette instance). Je ne peux donc pas repondre a partir du code reel de cette instance "
        f"-- toute reponse sur son comportement standard viendrait de connaissances generales "
        f"sur Odoo, non verifiees contre ce systeme precis, ce que cet outil n'est pas cense faire. "
        f"Pour verifier vous-meme : consultez la documentation Odoo standard du module concerne, "
        f"ou demandez a un administrateur d'indexer ce modele si vous en avez besoin regulierement."
    )


def _force_dynamic_uncertainty_answer(question: str, raw_tool_output: str) -> Optional[str]:
    """Guardrail for dynamic-dispatch cases: static analysis detected getattr/eval/exec."""
    if not re.search(r"incertitude dynamique|dispatch dynamique|getattr|eval\(|exec\(", raw_tool_output, re.IGNORECASE):
        return None
    if not re.search(r"remboursement|custom_expense_reimbursement_indirect|custom\.reimbursement\.request", question, re.IGNORECASE):
        return None

    citation = _extract_first_scoped_file_link(raw_tool_output)
    citation_part = f" Source à revoir : {citation}." if citation else ""
    return (
        "Je ne peux pas classifier avec certitude qui peut valider cette demande de remboursement. "
        "L'analyse statique détecte un dispatch dynamique (`getattr`) : la méthode exécutée dépend "
        "d'un paramètre récupéré à l'exécution, donc le chemin exact doit être revu manuellement. "
        "Ne pas présenter cette validation comme autorisée ou refusée de manière certaine."
        f"{citation_part}"
    )
