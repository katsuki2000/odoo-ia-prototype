"""Workflow state transition analysis (WorkflowState -> TRANSITIONS_VIA -> WorkflowState)."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Set
import networkx as nx

from code_intelligence.rules.common import NO_WORKFLOW_TRANSITION_MARKER, QueryStatus
from code_intelligence.rules.model_suggestions import model_not_found_message
from code_intelligence.rules.ontology import tags_for_node_attrs
from code_intelligence.utils import format_xml_id_citations
from core.evidence.evidence import Evidence, EvidenceSourceType, make_evidence
from code_intelligence.graph.workflow_extraction import workflow_transition_records


@dataclass
class WorkflowProcessResult:
    model_name: str
    status: QueryStatus = QueryStatus.NOT_FOUND
    states: List[str] = field(default_factory=list)
    transitions: List[Dict[str, Any]] = field(default_factory=list)
    # queried model's own behavioral_tags/technical_tags
    model_tags: List[str] = field(default_factory=list)
    summary_text: str = ""
    # structured Evidence produced at the source.
    evidence: List[Evidence] = field(default_factory=list)
    # state field of the model and the public methods that write it without a derived button transition
    state_field: str = ""
    state_methods: List[Dict[str, Any]] = field(default_factory=list)


def _state_overview_text(stateField: str, states: List[str], stateMethods: List[Dict[str, Any]]) -> str:
    """State values and the methods writing them, for a model whose view buttons yield no (or only some) transitions."""
    lines: List[str] = []
    if stateField and states:
        lines.append(f"The state field '{stateField}' has the values: {', '.join(states)}.")
    if stateMethods:
        lines.append("Methods that write this state field and are not linked to a derived button transition:")
        for entry in stateMethods:
            lines.append(
                f"- `{entry['method_name']}()` writes: {', '.join(entry['states'])}. The origin state, the callers and the "
                "checks inside the method are not derived here; read the method before concluding."
            )
    return "\n".join(lines)


def _build_workflow_evidence(
    model_name: str,
    transitions: List[Dict[str, Any]],
    states: List[str] = (),
    stateField: str = "",
    stateMethods: List[Dict[str, Any]] = (),
) -> List[Evidence]:
    """
    B1: one Evidence per TRANSITIONS_VIA edge actually found.
    """
    evidence: List[Evidence] = []

    for tr in transitions:
        origin = tr.get("origin_state", "")
        target = tr.get("target_state", "")
        method = tr.get("method_name", "")
        button = tr.get("button_label", "")
        req_groups = tr.get("required_groups", [])

        claim = (
            f"Model '{model_name}' transitions from '{origin}' to '{target}' "
            f"via button '{button}' (calls '{method}()')"
        )
        if req_groups:
            claim += f", restricted to groups: {', '.join(req_groups)}"

        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=claim,
            source=f"transition:{model_name}:{method}:{origin}:{target}:{button}",
            value=target,
            confidence="HIGH",
        ))

    if not transitions:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(
                f"No workflow state transition could be derived from the indexed code for model '{model_name}'. "
                "This does not prove that the model has no workflow; unsupported patterns may be absent from the graph."
            ),
            source=f"workflow:{model_name}",
            value="no_transition_derived",
            confidence="LOW",
        ))
        if stateField and states:
            evidence.append(make_evidence(
                source_type=EvidenceSourceType.CODE,
                claim=f"Model '{model_name}' has the state field '{stateField}' with the values: {', '.join(states)}.",
                source=f"state_field:{model_name}:{stateField}",
                value=",".join(states),
                confidence="HIGH",
            ))

    for entry in stateMethods:
        for state in entry["states"]:
            evidence.append(make_evidence(
                source_type=EvidenceSourceType.CODE,
                claim=(
                    f"Method '{entry['method_name']}()' of model '{model_name}' writes the state '{state}' on "
                    f"'{stateField}'; it is not linked to a derived button transition."
                ),
                source=f"state_write:{model_name}:{entry['method_name']}:{state}",
                value=state,
                confidence="HIGH",
            ))

    return evidence


def describe_workflow(
    G: nx.DiGraph,
    model_name: str
) -> WorkflowProcessResult:
    """
    Traverses WorkflowState -> TRANSITIONS_VIA -> WorkflowState edges.
    """
    model_node = f"model:{model_name}"

    if model_node not in G:
        return WorkflowProcessResult(
            model_name=model_name,
            status=QueryStatus.NOT_FOUND,
            summary_text=model_not_found_message(G, model_name)
        )

    states: Set[str] = set()
    transitions: List[Dict[str, Any]] = []

    for n, data in G.nodes(data=True):
        if data.get("node_type") == "WorkflowState" and data.get("model") == model_name:
            states.add(data.get("state_value", ""))

    for u, v, edge_data in G.edges(data=True):
        if edge_data.get("edge_type") == "TRANSITIONS_VIA":
            origin = G.nodes.get(u, {})
            target = G.nodes.get(v, {})
            if (
                origin.get("node_type") != "WorkflowState"
                or target.get("node_type") != "WorkflowState"
                or origin.get("model") != model_name
                or target.get("model") != model_name
            ):
                continue
            orig_st = origin.get("state_value", "")
            targ_st = target.get("state_value", "")
            for record in workflow_transition_records(edge_data):
                transitions.append({
                    "origin_state": orig_st,
                    "target_state": targ_st,
                    "method_name": record.get("method_name", ""),
                    "button_label": record.get("label_bouton", ""),
                    "required_groups": record.get("groupe_requis", []),
                    "alternative": bool(record.get("alternative", False)),
                })

    model_tags = tags_for_node_attrs(G.nodes[model_node])
    stateField = G.nodes[model_node].get("state_field", "")
    buttonMethods = {tr["method_name"] for tr in transitions}
    stateMethods = [
        entry for entry in (G.nodes[model_node].get("state_writes") or [])
        if not entry["method_name"].startswith("_") and entry["method_name"] not in buttonMethods
    ]
    sortedStates = sorted(list(states))

    if not transitions:
        summary = (
            f"{NO_WORKFLOW_TRANSITION_MARKER} for '{model_name}'. "
            "The graph may omit workflows expressed with unsupported patterns or fields."
        )
        overview = _state_overview_text(stateField, sortedStates, stateMethods)
        return WorkflowProcessResult(
            model_name=model_name,
            status=QueryStatus.EMPTY,
            states=sortedStates,
            model_tags=model_tags,
            summary_text=summary + ("\n" + overview if overview else ""),
            evidence=_build_workflow_evidence(model_name, transitions, sortedStates, stateField, stateMethods),
            state_field=stateField,
            state_methods=stateMethods,
        )

    steps_text = []
    for idx, tr in enumerate(transitions, 1):
        grp_str = ", ".join(tr["required_groups"]) if tr["required_groups"] else "All Users"
        _tr_citations = format_xml_id_citations(tr["required_groups"]) if tr["required_groups"] else ""
        _tr_suffix = f" ({_tr_citations})" if _tr_citations else ""
        steps_text.append(
            f"Step {idx}: [{tr['origin_state']}] -> [{tr['target_state']}] "
            f"via Button '{tr['button_label']}' (Method: `{tr['method_name']}()`, Role: [{grp_str}]){_tr_suffix}"
            + (" -- one of several possible outcomes of this button" if tr["alternative"] else "")
        )

    summary = f"Workflow Process for '{model_name}' ({len(transitions)} transitions):\n" + "\n".join(steps_text)
    if any(not tr["required_groups"] for tr in transitions):
        summary += (
            "\nNote: 'Role: [All Users]' means no group is declared on the button in the XML views; "
            "ACL, record rules and Python checks inside the method can still restrict who may use it."
        )
    overview = _state_overview_text(stateField, [], stateMethods)
    if overview:
        summary += "\n" + overview

    return WorkflowProcessResult(
        model_name=model_name,
        status=QueryStatus.FOUND,
        states=sortedStates,
        transitions=transitions,
        model_tags=model_tags,
        summary_text=summary,
        evidence=_build_workflow_evidence(model_name, transitions, sortedStates, stateField, stateMethods),
        state_field=stateField,
        state_methods=stateMethods,
    )
