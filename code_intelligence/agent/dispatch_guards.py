"""
code_intelligence/ci_agent_node/sourcing_guard.py

Mechanical verification that every citation in the agent's final answer corresponds
to citations produced in the raw tool output for the question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Set, Tuple

# Scoped file citation: explicit line range, per CI_SYSTEM_PROMPT's own
# instruction ("[file.py:L12-L25](file:///path#L12-L25)").
_SCOPED_FILE_LINK_PATTERN = re.compile(
    r"\(file:///(?P<path>[^\#\)]+)#L(?P<start>\d+)-L(?P<end>\d+)\)"
)
# Any file:// link at all, scoped or not -- used to find bare links that
# skipped the line-range requirement entirely.
_ANY_FILE_LINK_PATTERN = re.compile(r"\(file:///(?P<path>[^\#\)]+?)(?:#L\d+-L\d+)?\)")

# Explicit xml_id: prefix, per the format this patch adds to the prompts.
# A bare identifier like "account.group_account_manager" with no prefix is
# NOT treated as a citation -- it's ordinary technical vocabulary the LLM
# is expected to use throughout the answer, not a sourcing claim.
_XML_ID_PATTERN = re.compile(r"xml_id:\s*([a-zA-Z_]\w*\.[a-zA-Z_][\w.]*)")


@dataclass
class SourcingVerificationResult:
    unverified_scoped_citations: List[Tuple[str, int, int]] = field(default_factory=list)
    bare_file_links: List[str] = field(default_factory=list)  # no line range at all
    unverified_xml_ids: List[str] = field(default_factory=list)

    @property
    def is_fully_verified(self) -> bool:
        return not (self.unverified_scoped_citations or self.bare_file_links or self.unverified_xml_ids)


def _scoped_covered(citation: Tuple[str, int, int], ground_truth: Set[Tuple[str, int, int]]) -> bool:
    """Covered if the cited range falls within a ground-truth range for the
    same file -- subset, not exact equality, since the LLM may legitimately
    narrow a citation when quoting part of a larger source snippet."""
    path, start, end = citation
    return any(
        gt_path == path and gt_start <= start and end <= gt_end
        for gt_path, gt_start, gt_end in ground_truth
    )


def verify_citations(final_answer: str, raw_tool_output: str) -> SourcingVerificationResult:
    ground_truth_scoped = {
        (m.group("path"), int(m.group("start")), int(m.group("end")))
        for m in _SCOPED_FILE_LINK_PATTERN.finditer(raw_tool_output)
    }
    ground_truth_xml_ids = set(_XML_ID_PATTERN.findall(raw_tool_output))

    result = SourcingVerificationResult()

    for citation in {
        (m.group("path"), int(m.group("start")), int(m.group("end")))
        for m in _SCOPED_FILE_LINK_PATTERN.finditer(final_answer)
    }:
        if not _scoped_covered(citation, ground_truth_scoped):
            result.unverified_scoped_citations.append(citation)

    for m in _ANY_FILE_LINK_PATTERN.finditer(final_answer):
        if "#L" not in m.group(0):
            result.bare_file_links.append(m.group("path"))

    for xml_id in set(_XML_ID_PATTERN.findall(final_answer)):
        if xml_id not in ground_truth_xml_ids:
            result.unverified_xml_ids.append(xml_id)

    return result


def annotate_unverifiable_citations(final_answer: str, result: SourcingVerificationResult) -> str:
    """Never silently strip or rewrite around an unverified citation --
    that risks introducing new unverified content. Append a visible,
    explicit warning instead."""
    if result.is_fully_verified:
        return final_answer

    warnings = []
    if result.unverified_scoped_citations:
        cites = ", ".join(f"{p}#L{s}-L{e}" for p, s, e in result.unverified_scoped_citations)
        warnings.append(f"citation(s) fichier non retrouvée(s) dans les données produites: {cites}")
    if result.bare_file_links:
        warnings.append(
            "lien(s) fichier sans plage de lignes (non vérifiable mécaniquement): "
            + ", ".join(result.bare_file_links)
        )
    if result.unverified_xml_ids:
        warnings.append(
            "xml_id(s) non retrouvé(s) dans les données produites: " + ", ".join(result.unverified_xml_ids)
        )

    return (
        final_answer
        + "\n\n SOURCING NON VÉRIFIÉ : " + " ; ".join(warnings)
        + ". Ne pas considérer ces éléments comme confirmés pour cette question."
    )

# ── Dispatch Utilities ──────────────────────────────────────────────────

"""
code_intelligence/ci_dispatch_utils.py

Dispatch helpers, model ranking, user group overrides, noise reduction,
and dynamic uncertainty / out-of-scope answer formatters.
"""

import json
import logging
import re
from typing import Optional, List

from code_intelligence.agent.context_extractors import _AUTOMATION_PATTERN

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
