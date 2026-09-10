"""Evidence builder for server action static security analysis."""

from __future__ import annotations

from typing import Any, Dict, List
from core.evidence.evidence import Evidence, EvidenceSourceType, make_evidence


def build_server_action_evidence(
    action_xml_id: str,
    has_sudo: bool,
    trigger_conditions: List[str],
    sudo_call_count: int,
    hardcoded_id_lists: List[List[int]],
    dynamic_dispatch_patterns: List[str],
    group_checks: List[str],
) -> List[Evidence]:
    """Build structured Evidence for server action security checks."""
    scope: Dict[str, Any] = {}
    evidence: List[Evidence] = []

    if has_sudo:
        cond_clause = f", conditioned by: {'; '.join(trigger_conditions)}" if trigger_conditions else ""
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Server action '{action_xml_id}' calls sudo() ({sudo_call_count} call(s)), bypassing ir.rule and ACL checks{cond_clause}",
            source=f"server_action:{action_xml_id}:sudo",
            value=sudo_call_count,
            confidence="LOW",
            scope=scope,
        ))
    else:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Server action '{action_xml_id}' does not call sudo()",
            source=f"server_action:{action_xml_id}:sudo",
            value=None,
            confidence="LOW",
            scope=scope,
        ))

    if hardcoded_id_lists:
        for ids in hardcoded_id_lists:
            evidence.append(make_evidence(
                source_type=EvidenceSourceType.CODE,
                claim=f"Server action '{action_xml_id}' contains a hardcoded ID list: {ids}",
                source=f"server_action:{action_xml_id}:hardcoded_ids",
                value=ids,
                confidence="LOW",
                scope=scope,
            ))
    else:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Server action '{action_xml_id}' contains no hardcoded ID list",
            source=f"server_action:{action_xml_id}:hardcoded_ids",
            value=None,
            confidence="LOW",
            scope=scope,
        ))

    if dynamic_dispatch_patterns:
        for pattern_name in dynamic_dispatch_patterns:
            evidence.append(make_evidence(
                source_type=EvidenceSourceType.CODE,
                claim=f"Server action '{action_xml_id}' uses dynamic dispatch via {pattern_name}(), not statically classifiable",
                source=f"server_action:{action_xml_id}:dynamic_dispatch:{pattern_name}",
                value=pattern_name,
                confidence="LOW",
                scope=scope,
            ))
    else:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Server action '{action_xml_id}' uses no dynamic dispatch (getattr/eval/exec)",
            source=f"server_action:{action_xml_id}:dynamic_dispatch",
            value=None,
            confidence="LOW",
            scope=scope,
        ))

    if group_checks:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Server action '{action_xml_id}' checks group membership via has_group() for: {', '.join(sorted(group_checks))}",
            source=f"server_action:{action_xml_id}:group_checks",
            value=sorted(group_checks),
            confidence="LOW",
            scope=scope,
        ))
    else:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Server action '{action_xml_id}' contains no has_group() check",
            source=f"server_action:{action_xml_id}:group_checks",
            value=None,
            confidence="LOW",
            scope=scope,
        ))

    return evidence
