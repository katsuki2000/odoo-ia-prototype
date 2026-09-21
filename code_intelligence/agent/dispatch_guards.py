"""
code_intelligence/ci_agent_node/sourcing_guard.py

Mechanical verification that every citation in the agent's final answer corresponds
to citations produced in the raw tool output for the question.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set, Tuple

from code_intelligence.agent.source_definitions import definition_spans, range_overlaps_definition

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

# Fenced markdown code block (```...``` or ```python...```).
_CODE_FENCE_PATTERN = re.compile(r"```(?:\w+)?\n(.*?)```", re.DOTALL)
# Syntax markers that only appear in actual Python source, never in plain
# prose mentioning a method name in passing (e.g. "the action_confirm method").
_PYTHON_CODE_MARKERS_PATTERN = re.compile(
    r"@api\.\w+|^\s*def\s+\w+\(|raise\s+\w*(?:Error|Warning)\b|^\s*class\s+\w+\(",
    re.MULTILINE,
)
# How far (in characters) around a flagged code fence to look for a scoped
# citation before concluding the block is genuinely uncited -- wide enough
# to cover a citation given just before/after the block in the same answer
# section, narrow enough not to be satisfied by an unrelated citation from
# a completely different part of a long answer.
_CODE_BLOCK_CITATION_PROXIMITY_CHARS = 500


def _code_block_has_nearby_scoped_citation(answer: str, block_start: int, block_end: int) -> bool:
    window = answer[
        max(0, block_start - _CODE_BLOCK_CITATION_PROXIMITY_CHARS):
        block_end + _CODE_BLOCK_CITATION_PROXIMITY_CHARS
    ]
    return bool(_SCOPED_FILE_LINK_PATTERN.search(window))


@dataclass
class SourcingVerificationResult:
    unverified_scoped_citations: List[Tuple[str, int, int]] = field(default_factory=list)
    bare_file_links: List[str] = field(default_factory=list)  # no line range at all
    unverified_xml_ids: List[str] = field(default_factory=list)
    # todo/contexte.txt section 814: fenced code blocks presenting Python
    # syntax (def/@api.../raise) as if real, with no scoped file:// citation
    # anywhere nearby -- the pattern behind the invented `_check_name` method
    # on ACC-Q5 (section 812), which carried no citation of its own and so
    # was invisible to the 3 checks above (none of which look at prose that
    # never attempts a file:// link at all).
    uncited_code_blocks: List[str] = field(default_factory=list)

    @property
    def is_fully_verified(self) -> bool:
        return not (
            self.unverified_scoped_citations or self.bare_file_links
            or self.unverified_xml_ids or self.uncited_code_blocks
        )


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

    for m in _CODE_FENCE_PATTERN.finditer(final_answer):
        block = m.group(1)
        if _PYTHON_CODE_MARKERS_PATTERN.search(block) and not _code_block_has_nearby_scoped_citation(
            final_answer, m.start(), m.end()
        ):
            result.uncited_code_blocks.append(block.strip()[:200])

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
    if result.uncited_code_blocks:
        warnings.append(
            "bloc(s) de code présenté(s) comme réel(s) sans aucune citation file:// à proximité "
            "(possible invention): " + " ||| ".join(result.uncited_code_blocks)
        )

    return (
        final_answer
        + "\n\n SOURCING NON VÉRIFIÉ : " + " ; ".join(warnings)
        + ". Ne pas considérer ces éléments comme confirmés pour cette question."
    )


# todo/plan_4.1_citation_as_constraint.md / todo/contexte.txt sections 870-873:
# citation-as-constraint. verify_citations() above only WARNS when a code
# block presenting real Python syntax has no nearby scoped citation --
# the fabricated block itself stays visible to the user. This substitutes
# it with the real source read from disk or strips it entirely -- never
# left displayed as fabricated text, warned or not. A block naming a
# def/class is only backed by the cited ranges overlapping that definition
# in the real file: a citation pointing at another definition strips the
# block instead of substituting unrelated real code (section 872).
_STRIPPED_CODE_BLOCK_NOTE = (
    "*(bloc de code omis : non retrouvé verbatim dans les observations "
    "produites pour cette question -- voir la/les citation(s) file:// "
    "à proximité pour le contenu réel.)*"
)


def _nearby_scoped_citations(
    answer: str, block_start: int, block_end: int
) -> List[Tuple[str, int, int]]:
    window = answer[
        max(0, block_start - _CODE_BLOCK_CITATION_PROXIMITY_CHARS):
        block_end + _CODE_BLOCK_CITATION_PROXIMITY_CHARS
    ]
    return [
        (m.group("path"), int(m.group("start")), int(m.group("end")))
        for m in _SCOPED_FILE_LINK_PATTERN.finditer(window)
    ]


_BLOCK_DEFINITION_PATTERN = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+(\w+)", re.MULTILINE)


def _defined_names(block: str) -> List[str]:
    return list(dict.fromkeys(_BLOCK_DEFINITION_PATTERN.findall(block)))


def _ranges_backing_definitions(
    path: Path, names: List[str], ranges: List[Tuple[int, int]]
) -> Optional[List[Tuple[int, int]]]:
    """Cited ranges overlapping a definition the block names; None when a
    name has no such range or the file cannot be parsed."""
    spans = definition_spans(path)
    if spans is None:
        return None
    backing = {
        name: [r for r in ranges if range_overlaps_definition(spans, name, *r)]
        for name in names
    }
    if not all(backing.values()):
        return None
    return sorted({r for matching in backing.values() for r in matching})


def _unbacked_definition_note(names: List[str], ranges: List[Tuple[int, int]]) -> str:
    cited = ", ".join(f"L{s}-L{e}" for s, e in sorted(set(ranges)))
    defined = ", ".join(f"`{n}`" for n in names)
    return (
        f"*(bloc de code omis : la plage citée ({cited}) n'a pas pu être rattachée "
        f"à la définition de {defined} -- citation à ne pas considérer comme confirmée.)*"
    )


def substitute_or_strip_code_blocks(final_answer: str) -> str:
    """Replace every fenced code block that presents real Python syntax
    (see _PYTHON_CODE_MARKERS_PATTERN) with the actual source lines read
    from disk, or strip it, depending on the scoped citation(s) found
    nearby (same proximity window as verify_citations' uncited_code_blocks
    check). Meant to run BEFORE verify_citations in the post-processing
    pipeline: a substituted block is now genuinely covered by its own
    nearby citation and will not be re-flagged; a stripped block is no
    longer a fenced code block at all."""
    from code_intelligence.agent.tools.introspection import read_precise_source_code

    _log = logging.getLogger(__name__)

    def _replace(match: "re.Match") -> str:
        block = match.group(1)
        if not _PYTHON_CODE_MARKERS_PATTERN.search(block):
            return match.group(0)

        citations = _nearby_scoped_citations(final_answer, match.start(), match.end())
        # The regex path group never includes the leading '/' consumed by
        # the literal 'file:///' prefix -- restore it before touching disk.
        paths = {("/" + path) for path, _s, _e in citations}

        if len(paths) != 1:
            _log.warning(
                "Node [code_intelligence_agent]: stripping fabricated-looking "
                "code block (%s) -- see todo/contexte.txt section 870, "
                "todo/plan_4.1_citation_as_constraint.md.",
                "no nearby citation" if not citations else "citations span multiple files",
            )
            return _STRIPPED_CODE_BLOCK_NOTE

        path = next(iter(paths))
        cited = [(s, e) for _p, s, e in citations]
        names = _defined_names(block)
        backing = _ranges_backing_definitions(Path(path), names, cited) if names else cited
        if backing is None:
            _log.warning(
                "Node [code_intelligence_agent]: stripping code block -- cited "
                "range(s) do not back definition(s) %s. See todo/contexte.txt "
                "sections 872-873.",
                names,
            )
            return _unbacked_definition_note(names, cited)

        line_start = min(s for s, _e in backing)
        line_end = max(e for _s, e in backing)
        real_snippet = read_precise_source_code(path, line_start, line_end)
        if real_snippet.startswith("Error"):
            _log.warning(
                "Node [code_intelligence_agent]: stripping fabricated-looking "
                "code block -- read_precise_source_code failed (%s). See "
                "todo/contexte.txt section 870, todo/plan_4.1_citation_as_constraint.md.",
                real_snippet,
            )
            return _STRIPPED_CODE_BLOCK_NOTE

        return f"```\n{real_snippet}\n```"

    return _CODE_FENCE_PATTERN.sub(_replace, final_answer)

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

from code_intelligence.agent.context_extractors import (
    _AUTOMATION_PATTERN,
    _question_is_security_distinction_related,
)

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


# Tools that already surface the ACL/ir.rule (surface-level access) layer,
# vs. tools that actually look at the Python application-level guard.
_ACL_LAYER_TOOLS = frozenset({"who_has_access_to", "evaluate_record_rules"})
_APPLICATION_GUARD_TOOLS = frozenset({"read_source_code", "analyze_method_override_chain"})

# todo/contexte.txt section 813/814: broader than _ACL_LAYER_TOOLS/
# _APPLICATION_GUARD_TOOLS above (which target the narrow "distinction
# between two groups" mid-loop reminder only). Used at SYNTHESIS time to
# decide whether a confident absolute-absence claim ("aucune restriction",
# "en l'absence de tout verrou") is safe to let through unqualified. On
# ACC-Q2, only access/permission-layer tools ran (who_has_access_to,
# evaluate_record_rules, analyze_security_locks, button_execution_path) --
# the real restriction lived in a workflow/date-lock check
# (_check_fiscalyear_lock_date/_get_user_fiscal_lock_date) that none of
# those tools surface, and the question's phrasing never matched the
# narrow _question_is_security_distinction_related pattern, so the
# existing mid-loop reminder never fired either. A separate, coarser
# check at synthesis time: not a replacement for fixing tool dispatch
# (that root cause is tracked separately), just a last-resort guard
# against presenting an under-covered investigation as a definitive verdict.
_ACCESS_LAYER_ONLY_TOOLS = frozenset({
    "who_has_access_to", "evaluate_record_rules", "analyze_security_locks", "button_execution_path",
})
_DEEPER_COVERAGE_TOOLS = frozenset({
    "read_source_code", "analyze_method_override_chain", "describe_workflow",
})


def tools_lack_deeper_coverage(tool_observation_tools: Optional[List[str]]) -> bool:
    """True when every tool actually invoked this turn belongs to the
    access/permission layer and none of the deeper workflow/source-level
    tools were ever called -- signals that a confident absence claim in
    the synthesized answer would be based on partial coverage only."""
    if not tool_observation_tools:
        return False
    tools_seen = set(tool_observation_tools)
    if not (tools_seen & _ACCESS_LAYER_ONLY_TOOLS):
        return False
    return not (tools_seen & _DEEPER_COVERAGE_TOOLS)


def _maybe_build_application_layer_reminder(question: str, tool_observation_tools: List[str]) -> Optional[str]:
    """Mid-loop nudge: push the ReAct loop to check the Python-level
    application guard before concluding 'no distinction' from ACL/ir.rule
    alone on a security-distinction question.

    todo/contexte.txt section 778: on PUR-Q1 the agent called
    who_has_access_to + evaluate_record_rules, found identical ACL/ir.rule
    across the two groups the question compares, and concluded (wrongly)
    that no distinction exists at all -- without ever calling
    read_source_code on the real application-level guard (_approval_allowed(),
    invoked from button_confirm()/button_approve()). assess_evidence_sufficiency()
    cannot catch this after the fact (its check is lexical -- 'observation
    found' vs 'not found', never 'does this actually answer the question
    asked') and the RAG fallback would not help either (documents only, no
    code, since 30/08 -- see todo/plan.md). The ReAct loop's own tool
    selection is therefore the only point where this can be corrected, and
    only before it settles on a final answer -- hence a SystemMessage
    injected between tool-selection turns, not a post-hoc check."""
    if not _question_is_security_distinction_related(question):
        return None
    tools_seen = set(tool_observation_tools)
    if not (_ACL_LAYER_TOOLS & tools_seen):
        return None
    if _APPLICATION_GUARD_TOOLS & tools_seen:
        return None
    return (
        "RAPPEL : l'ACL et les ir.rule seuls ne suffisent pas toujours à répondre à "
        "une question de distinction entre deux rôles/groupes -- si les permissions "
        "semblent identiques entre les groupes comparés dans la question, ne conclus "
        "PAS encore à une absence de distinction. Vérifie le garde applicatif Python "
        "(ex. méthode d'approbation/de validation invoquée depuis un bouton, souvent "
        "nommée _*_allowed/_check_*/button_*) avec read_source_code avant de répondre."
    )
