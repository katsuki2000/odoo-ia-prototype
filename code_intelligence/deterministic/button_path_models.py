"""
code_intelligence/deterministic/button_path_models.py

Data structures and evidence generation for Odoo button execution paths and UI field inspection.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Set

from core.evidence import Evidence, EvidenceSourceType, make_evidence


@dataclass
class ButtonExecutionPathResult:
    button_identifier: str
    model_name: str
    method_name: str = ""
    origin_states: List[str] = field(default_factory=list)
    target_state: str = ""
    required_groups: List[str] = field(default_factory=list)
    execution_steps: List[str] = field(default_factory=list)
    summary_text: str = ""
    # Whether the button is available to the requester
    available_to_requester: Optional[bool] = None
    unavailable_reason: str = ""
    # Bloc P2 Jour 4: called method's own behavioral_tags/technical_tags
    method_tags: List[str] = field(default_factory=list)
    # B1 replication of the B0 pilot: structured Evidence produced at the source.
    evidence: List[Evidence] = field(default_factory=list)


def _build_button_execution_evidence(
    button_label_or_name: str,
    model_name: str,
    method_name: str,
    method_exists: bool,
    origin_states: Set[str],
    target_state: str,
    required_groups: Set[str],
    user_groups: Optional[List[str]],
    available_to_requester: Optional[bool],
) -> List[Evidence]:
    """
    B1: four structural facts, each always asserted explicitly.
    """
    evidence: List[Evidence] = []

    evidence.append(make_evidence(
        source_type=EvidenceSourceType.CODE,
        claim=(
            f"Button '{button_label_or_name}' on '{model_name}' calls method "
            f"'{method_name}()' (method_exists={method_exists})"
        ),
        source=f"method:{model_name}.{method_name}",
        value=method_name,
        confidence="HIGH",
    ))

    if origin_states and target_state:
        origins_str = ", ".join(sorted(origin_states))
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(
                f"Button '{button_label_or_name}' transitions '{model_name}' "
                f"from [{origins_str}] to '{target_state}'"
            ),
            source=f"transition:{model_name}:{method_name}",
            value=target_state,
            confidence="HIGH",
        ))
    else:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Button '{button_label_or_name}' on '{model_name}' triggers no workflow state transition",
            source=f"transition:{model_name}:{method_name}",
            value=None,
            confidence="HIGH",
        ))

    if required_groups:
        grp_str = ", ".join(sorted(required_groups))
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Button '{button_label_or_name}' on '{model_name}' is restricted to groups: {grp_str}",
            source=f"button_security:{model_name}:{method_name}",
            value=sorted(required_groups),
            confidence="HIGH",
        ))
    else:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Button '{button_label_or_name}' on '{model_name}' carries no button-level group restriction",
            source=f"button_security:{model_name}:{method_name}",
            value=None,
            confidence="HIGH",
        ))

    if user_groups is not None:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(
                f"Button '{button_label_or_name}' on '{model_name}' is "
                f"{'available' if available_to_requester else 'NOT available'} to this requester"
            ),
            source=f"button_availability:{model_name}:{method_name}",
            value=available_to_requester,
            confidence="HIGH",
            scope={"user_groups": sorted(user_groups)},
        ))

    return evidence
