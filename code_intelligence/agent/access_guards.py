"""
code_intelligence/ci_access_guards.py

Extraction, grounding, and scoping helpers for technical user groups,
core-only stripping, and custom module boundary enforcement.
"""

import logging
from pathlib import Path
import re
from typing import List, Optional, Tuple, Dict

from code_intelligence.utils import (
    _match_near_truncation,
    _extract_amount,
    _question_is_approval_related,
    _LOCK_CONDITION_LINE_RE,
    _AMOUNT_CMP_RE,
)
logger = logging.getLogger(__name__)

_REQUIRED_GROUP_LINE_RE = re.compile(
    r"Groupe\(s\)\s+technique\(s\)\s+requis\s+detecte\(s\)\s+\(has_group\):\s*([^\n]+)"
)
_GROUP_XMLID_RE = re.compile(r"\b[a-z][a-z0-9_]*\.group_[a-z0-9_]+\b")
# Section 948 (todo/contexte.txt): evaluate_record_rules' own "(groupes: ...)"
# formatting (record_rules.py::_format_rule_groups) is a second, distinct
# grounding path for a group xml_id -- neither the has_group()-only
# _REQUIRED_GROUP_LINE_RE below nor the "xml_id:"-prefixed _XML_ID_PATTERN
# (dispatch_guards.py) recognize it, since the group xmlid here is written
# bare in backticks/parens, never preceded by the literal "xml_id:". Nested
# parens (the group's own display name, e.g. "('User: All Documents')")
# make a naive "[^)]*" insufficient -- same nested-paren shape already
# handled by _GROUP_ESCALATION_SEE_ALL_RE further below.
_GROUPES_BLOCK_RE = re.compile(r"\(groupes:\s*(?P<groups>[^)]*(?:\([^()]*\)[^)]*)*)\)")


def _extract_required_groups(raw_tool_output: str) -> List[str]:
    """Pull every has_group()-derived required group xml_id out of raw tool text."""
    groups: List[str] = []
    for match in _REQUIRED_GROUP_LINE_RE.finditer(raw_tool_output):
        for name in match.group(1).split(","):
            name = name.strip()
            if name and name not in groups:
                groups.append(name)
    return groups


def _extract_record_rule_groups(raw_tool_output: str) -> List[str]:
    """Pull every group xml_id grounded via evaluate_record_rules' own
    '(groupes: ...)' formatting -- a distinct grounding path from
    has_group()/analyze_security_locks, not covered by
    _extract_required_groups. See todo/contexte.txt section 948 (SAL-Q1
    rejeu: the section 946 group-escalation backfill wrote a group xmlid
    sourced verbatim from this exact formatting, and the ungrounded-xmlid
    guard below flagged it as a possible hallucination because it only
    recognized has_group()-style grounding)."""
    groups: List[str] = []
    for match in _GROUPES_BLOCK_RE.finditer(raw_tool_output):
        for xmlid in _GROUP_XMLID_RE.findall(match.group("groups")):
            if xmlid not in groups:
                groups.append(xmlid)
    return groups


def _flag_ungrounded_group_xmlids(final_answer: str, raw_tool_output: str) -> str:
    """Flag group XML-IDs in final_answer with no backing in tool observations."""
    from .dispatch_guards import _XML_ID_PATTERN
    grounded = (
        set(_extract_required_groups(raw_tool_output))
        | set(_XML_ID_PATTERN.findall(raw_tool_output))
        | set(_extract_record_rule_groups(raw_tool_output))
        | set(_GROUP_XMLID_RE.findall(raw_tool_output))
    )
    if not grounded:
        return final_answer

    mentioned = set(_GROUP_XMLID_RE.findall(final_answer))
    ungrounded = sorted(mentioned - grounded)
    if not ungrounded:
        return final_answer

    group_list = ", ".join(ungrounded)
    logger.warning(
        "Node [code_intelligence_agent]: group xmlid(s) mentioned in synthesized "
        "answer with no has_group() backing in this turn's scoped tool output "
        "(possible hallucination, flagged not stripped): %s",
        group_list,
    )
    return (
        final_answer
        + f"\n\n GROUPE(S) NON VÉRIFIÉ(S) : {group_list} mentionné(s) dans la réponse "
        f"sans correspondance has_group() dans les données produites pour cette question. "
        f"Ne pas considérer ce(s) groupe(s) comme confirmé(s) sans vérification manuelle."
    )


_SENTENCE_SPLIT_RE = re.compile(
    r"(?<=[.!?])\s+(?=[A-Z\u00c0\u00c2\u00c4\u00c9\u00c8\u00ca\u00cb\u00ce\u00cf\u00d4\u00d6\u00d9\u00db\u00dc\u00c7])"
)


def _grounded_core_only_groups(final_answer: str, scoped_tool_output: str) -> List[str]:
    """Find group XML-IDs grounded only in core Odoo when a custom override also exists.

    Section 849 (todo/contexte.txt): this heuristic was designed and tested
    for exactly one scenario -- a single core-only group superseded by a
    single competing custom-module group deciding the SAME thing (see
    test_bloc9_07_core_only_group_stripping.py). When several DISTINCT
    core-only groups are grounded in the evidence at once (e.g. a write-ACL
    group and an unrelated approval-workflow group), that is evidence they
    are independent facts, not a 1-for-1 override -- stripping any of them
    then silently deletes a correct, unrelated finding (ACC-Q1, section
    848/849: account.group_account_invoice, an ACL fact, wrongly stripped
    because a custom module happened to exist for a different, unrelated
    approval workflow). Bail out entirely rather than guess which of
    several core-only groups (if any) is actually superseded.

    Section 850 fix-of-a-fix: the bail-out count must be taken over the
    FULL set of core-only groups grounded in the evidence, not just the
    subset the synthesized answer happens to mention -- a write-focused
    question naturally only cites account.group_account_invoice and never
    mentions the other two unrelated core-only groups (base.group_portal,
    base.group_public), so counting on `mentioned` undercounted to 1 and
    never bailed out (confirmed 4/4 on a real ACC-Q1 replay). Whether
    several independent core-only facts exist is a property of the
    evidence, not of what the LLM chose to write about.
    """
    grounded = set(_extract_required_groups(scoped_tool_output))
    if not grounded:
        return []
    custom_grounded = set(
        _extract_required_groups(_restrict_blocks_to_custom_modules(scoped_tool_output))
    )
    if not custom_grounded:
        return []
    all_core_only = grounded - custom_grounded
    if len(all_core_only) > 1:
        return []
    mentioned = set(_GROUP_XMLID_RE.findall(final_answer))
    return sorted(mentioned & all_core_only)


def _strip_core_only_group_mentions(final_answer: str, scoped_tool_output: str) -> str:
    """Remove mentions of group XML-IDs superseded by custom-module groups."""
    core_only = _grounded_core_only_groups(final_answer, scoped_tool_output)
    if not core_only:
        return final_answer

    def _contains_core_only(fragment: str) -> bool:
        return any(xmlid in fragment for xmlid in core_only)

    kept_paragraphs = []
    for para in final_answer.split("\n\n"):
        if not _contains_core_only(para):
            kept_paragraphs.append(para)
            continue

        lines = para.split("\n")
        if len(lines) > 1 and any(l.strip().startswith(("-", "*")) for l in lines):
            kept_lines = [l for l in lines if not _contains_core_only(l)]
            if kept_lines:
                kept_paragraphs.append("\n".join(kept_lines))
        elif len(lines) == 1:
            sentences = _SENTENCE_SPLIT_RE.split(para)
            kept_sentences = [s for s in sentences if not _contains_core_only(s)]
            if kept_sentences:
                kept_paragraphs.append(" ".join(kept_sentences))

    result = "\n\n".join(kept_paragraphs)
    logger.warning(
        "Node [code_intelligence_agent]: stripped grounded-but-core-Odoo-only "
        "group xmlid(s) from synthesized answer: %s",
        ", ".join(core_only),
    )
    return result


def _scoped_raw_tool_output(
    tool_observations: List[str],
    tool_observation_models: List[str],
    target_models: List[str],
) -> str:
    """Restrict raw tool output to observations relevant to target_models."""
    if not target_models:
        return "\n\n".join(tool_observations)
    target_set = set(target_models)
    scoped = [
        obs
        for obs, model in zip(tool_observations, tool_observation_models)
        if model and model in target_set
    ]
    return "\n\n".join(scoped)


def _extract_required_groups_for_amount(raw_tool_output: str, amount: Optional[float] = None) -> List[str]:
    """Pull required group xml_ids from raw tool text, filtered by amount threshold."""
    all_groups = _extract_required_groups(raw_tool_output)
    if amount is None or not all_groups:
        return all_groups

    group_conditions: Dict[str, List[Tuple[str, float]]] = {}
    for match in _LOCK_CONDITION_LINE_RE.finditer(raw_tool_output):
        if _match_near_truncation(raw_tool_output, match.start(), match.end()):
            continue
        cond_text = match.group(1)
        group_name = match.group(2).strip()
        cmp_match = _AMOUNT_CMP_RE.search(cond_text)
        if cmp_match:
            op = cmp_match.group(1)
            thresh = float(cmp_match.group(2))
            group_conditions.setdefault(group_name, []).append((op, thresh))

    filtered_groups: List[str] = []
    for g in all_groups:
        if g not in group_conditions:
            filtered_groups.append(g)
        else:
            active = False
            for op, thresh in group_conditions[g]:
                if op == ">" and amount > thresh:
                    active = True
                    break
                elif op == ">=" and amount >= thresh:
                    active = True
                    break
                elif op == "<" and amount < thresh:
                    active = True
                    break
                elif op == "<=" and amount <= thresh:
                    active = True
                    break
            if active:
                filtered_groups.append(g)

    return filtered_groups


_BLOCK_FILE_LINK_RE = re.compile(r"\(file://([^)#]+)")


def _block_is_custom_module_file(block: str) -> bool:
    """True when file link points to an installed custom module rather than core Odoo."""
    match = _BLOCK_FILE_LINK_RE.search(block)
    if not match:
        return True
    from config.settings import CORE_ADDONS_PATH, CORE_FRAMEWORK_ADDONS_PATH, CUSTOM_ADDONS_PATH
    try:
        resolved = Path(match.group(1)).resolve()
        if CUSTOM_ADDONS_PATH and Path(CUSTOM_ADDONS_PATH).resolve() in resolved.parents:
            return True
        if CORE_ADDONS_PATH and Path(CORE_ADDONS_PATH).resolve() in resolved.parents:
            try:
                rel = resolved.relative_to(Path(CORE_ADDONS_PATH).resolve())
                if rel.parts and rel.parts[0].startswith("custom"):
                    return True
            except ValueError:
                pass
            return False
        if CORE_FRAMEWORK_ADDONS_PATH and Path(CORE_FRAMEWORK_ADDONS_PATH).resolve() in resolved.parents:
            return False
    except Exception:
        pass
    path_parts = Path(match.group(1)).parts
    if any(part.startswith("custom") for part in path_parts):
        return True
    core_dirs = {"base", "web", "odoo"}
    if any(part in core_dirs for part in path_parts):
        return False
    return True


def _restrict_blocks_to_custom_modules(raw_tool_output: str) -> str:
    """Drop blocks whose file link points outside a custom module."""
    blocks = raw_tool_output.split("\n\n")
    kept = [b for b in blocks if _block_is_custom_module_file(b)]
    return "\n\n".join(kept) if kept else raw_tool_output


def _backfill_missing_required_groups(final_answer: str, raw_tool_output: str, question: str) -> str:
    """Backfill required groups detected in code if absent from synthesized answer."""
    if not _question_is_approval_related(question):
        return final_answer

    amount = _extract_amount(question)
    custom_scoped_output = _restrict_blocks_to_custom_modules(raw_tool_output)
    required_groups = _extract_required_groups_for_amount(custom_scoped_output, amount)
    if not required_groups:
        return final_answer

    group_list = ", ".join(required_groups)
    logger.info(
        "Node [code_intelligence_agent]: backfilling required group(s) missing "
        "from synthesized answer: %s",
        group_list,
    )
    return (
        final_answer
        + f"\n\n[FAIT DÉTERMINISTIQUE] Groupe(s) technique(s) requis (has_group) "
        f"détecté(s) dans le code pour cette action : {group_list}. Fait extrait "
        f"directement de l'analyse statique du code."
    )


_IMPLIED_IDS_PATTERN = re.compile(
    r"(?P<child>[a-zA-Z_][\w.]*)(?:\s*\('[^']*'\))?\s+\(via implied_ids <-\s*(?P<parent>[a-zA-Z_][\w.]*)"
)
_INHERITANCE_VERBALIZATION_RE = re.compile(
    r"\b(?:implied_ids|h[eé]rite|h[eé]ritent|implication|transiti\w*)\b",
    re.IGNORECASE,
)
_UI_ACCESS_QUESTION_RE = re.compile(
    r"\b(?:champ|bouton|visible|visibilit[eé]|interface|field|button|"
    r"compte\s+comptable|ligne\s+de\s+facture)\b",
    re.IGNORECASE,
)
_DIRECT_ACL_NEGATION_RE = re.compile(
    r"^\s*[-*]\s+L['’]ACL directe.*?"
    r"(?:ne limite que la lecture|ne restreint pas les opérations).*?(?=\n\s*[-*]\s|\n\s*\n|\Z)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)


def _remove_false_direct_acl_explanation(final_answer: str) -> str:
    """Remove the claim that a zero permission in one ACL is non-restrictive."""
    return _DIRECT_ACL_NEGATION_RE.sub("", final_answer).rstrip()


def _backfill_missing_implied_ids_mechanism(
    final_answer: str, raw_tool_output: str, question: str = ""
) -> str:
    """Section 918 (ACC-Q1): when who_has_access_to reveals permissions inherited
    via implied_ids for a group discussed in the question/answer, ensure the
    answer explains this inheritance rather than flattening it into a direct ACL.
    """
    if question and _UI_ACCESS_QUESTION_RE.search(question):
        return final_answer
    matches = list(_IMPLIED_IDS_PATTERN.finditer(raw_tool_output))
    if not matches:
        return final_answer

    combined_context = f"{question} {final_answer}"
    for match in matches:
        child_group = match.group("child")
        parent_group = match.group("parent")
        child_short = child_group.split(".")[-1]
        parent_short = parent_group.split(".")[-1]

        if child_group not in combined_context and child_short not in combined_context:
            continue

        logger.info(
            "Node [code_intelligence_agent]: backfilling missing implied_ids "
            "inheritance mechanism for %s <- %s",
            child_group, parent_group,
        )
        final_answer = _remove_false_direct_acl_explanation(final_answer)
        return (
            final_answer
            + f"\n\n[FAIT DÉTERMINISTIQUE] Précision d'héritage de droits : pour la permission "
            f"concernée, `{child_group}` hérite de l'ACL de `{parent_group}` par implication "
            f"transitive (`implied_ids`). Les ACL applicables sont additives : l'absence d'une "
            f"permission dans une ACL directe ne retire pas le droit accordé par une autre ACL applicable."
        )

    return final_answer


_IGNORED_GROUP_LINE_RE = re.compile(
    r"Règles de Groupe ignorées \(non-membre\):\s*(?P<body>[^\n]+)"
)
# The two domain_force literals Odoo uses idiomatically for an unrestricted
# "sees everything" group rule -- already special-cased identically in
# RuleEvaluationResult.can_view_amount (record_rules.py). Recognizing the
# same two literals here reuses an existing, documented Odoo-wide
# convention (e.g. sale_order_see_all, account_invoice_rule_see_all),
# not a per-module special case.
_GROUP_ESCALATION_SEE_ALL_RE = re.compile(
    r"(?P<rule_name>[^,()]+?)"
    r"\s*\(groupes:\s*(?P<groups>[^)]*(?:\([^()]*\)[^)]*)*)\)"
    r"\s*\[(?:\[\(1,\s*'='\s*,\s*1\)\]\]|\[\('id',\s*'!='\s*,\s*False\)\]\])"
    r"\s*\(xml_id:\s*(?P<rule_xmlid>[\w.]+)\)"
)


def _backfill_missing_group_escalation_note(
    final_answer: str, raw_tool_output: str, question: str
) -> str:
    """Section 946: evaluate_record_rules lists, among the ignored
    (non-member) group rules, an "All X" style rule using Odoo's standard
    unrestricted-access idiom. When the question explicitly names that
    escalation group (typically to exclude it -- e.g. 'sans
    group_sale_salesman_all_leads'), the synthesized answer must not drop
    the contrast: a requester who also belonged to that group would face
    no restriction at all. Backfilled verbatim from the tool's own ignored-
    rule listing -- never invented, and only when the question itself
    raises the group (avoids cluttering every access answer with it)."""
    if question and _UI_ACCESS_QUESTION_RE.search(question):
        return final_answer
    for line_match in _IGNORED_GROUP_LINE_RE.finditer(raw_tool_output):
        body = line_match.group("body")
        for entry in _GROUP_ESCALATION_SEE_ALL_RE.finditer(body):
            groups_text = entry.group("groups")
            group_xmlids = _GROUP_XMLID_RE.findall(groups_text)
            if not group_xmlids:
                continue
            group_xmlid = group_xmlids[0]
            group_short = group_xmlid.split(".")[-1]
            if group_xmlid not in question and group_short not in question:
                continue
            rule_xmlid = entry.group("rule_xmlid")
            rule_short = rule_xmlid.split(".")[-1]
            label_match = re.search(re.escape(group_xmlid) + r"\s*\('([^']*)'\)", groups_text)
            group_label = label_match.group(1) if label_match else group_short
            rule_name = entry.group("rule_name").strip()
            logger.info(
                "Node [code_intelligence_agent]: backfilling missing group-escalation "
                "contrast for %s (rule %s)", group_xmlid, rule_xmlid,
            )
            return (
                final_answer
                + f"\n\n[FAIT DÉTERMINISTIQUE] Un utilisateur appartenant en plus au groupe "
                f"`{group_xmlid}` ('{group_label}') ne serait plus soumis à cette restriction : "
                f"la règle '{rule_name}' (xml_id: {rule_xmlid}) lève alors toute limitation pour "
                f"ce modèle."
            )
    return final_answer
