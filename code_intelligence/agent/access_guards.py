"""
code_intelligence/ci_access_guards.py

Extraction, grounding, and scoping helpers for technical user groups,
core-only stripping, and custom module boundary enforcement.
"""

import logging
import re
from typing import List

from core.verification.extractors import GROUP_XMLID_RE as _GROUP_XMLID_RE
logger = logging.getLogger(__name__)

_REQUIRED_GROUP_LINE_RE = re.compile(
    r"Groupe\(s\)\s+technique\(s\)\s+requis\s+detecte\(s\)\s+\(has_group\):\s*([^\n]+)"
)

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


_UI_ACCESS_QUESTION_RE = re.compile(
    r"\b(?:champ|bouton|visible|visibilit[eé]|interface|field|button|"
    r"compte\s+comptable|ligne\s+de\s+facture)\b",
    re.IGNORECASE,
)


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
    """evaluate_record_rules lists, among the ignored
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
