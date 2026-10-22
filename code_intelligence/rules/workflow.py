"""
code_intelligence/deterministic/workflow_process.py

Workflow state transition graph analysis (WorkflowState -> TRANSITIONS_VIA -> WorkflowState).
"""

import ast
from dataclasses import dataclass, field
import logging
import textwrap
from typing import Any, Dict, List, Set
import networkx as nx

logger = logging.getLogger(__name__)

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


def _build_workflow_evidence(
    model_name: str,
    transitions: List[Dict[str, Any]],
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

    if not transitions:
        return WorkflowProcessResult(
            model_name=model_name,
            status=QueryStatus.EMPTY,
            states=sorted(list(states)),
            model_tags=model_tags,
            summary_text=(
                f"{NO_WORKFLOW_TRANSITION_MARKER} for '{model_name}'. "
                "The graph may omit workflows expressed with unsupported patterns or fields."
            ),
            evidence=_build_workflow_evidence(model_name, transitions),
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

    return WorkflowProcessResult(
        model_name=model_name,
        status=QueryStatus.FOUND,
        states=sorted(list(states)),
        transitions=transitions,
        model_tags=model_tags,
        summary_text=summary,
        evidence=_build_workflow_evidence(model_name, transitions),
    )




def inspect_stage_workflow_actions(source_text: str) -> dict:
    """Inspect AST of a write() method to detect automatic stage-driven actions
    (recurrence duplication via copy(), close_date assignment, kanban reset, activity updates)."""
    if not source_text or not source_text.strip():
        return {}
    try:
        tree = ast.parse(textwrap.dedent(source_text))
    except SyntaxError:
        return {}

    actions = {
        "has_recurrence_copy": False,
        "copy_conditions": [],
        "has_close_date": False,
        "has_kanban_reset": False,
        "has_activity_update": False,
        "followers_condition": None,
    }

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.if_stack = []

        def visit_If(self, node):
            try:
                cond = ast.unparse(node.test)
            except Exception:
                cond = ""
            self.if_stack.append(cond)
            self.generic_visit(node)
            self.if_stack.pop()

        def visit_Call(self, node):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr == "copy":
                    actions["has_recurrence_copy"] = True
                    actions["copy_conditions"].extend(self.if_stack)
                elif node.func.attr in ("activity_feedback", "activity_update"):
                    actions["has_activity_update"] = True
                elif node.func.attr == "_add_followers":
                    actions["followers_condition"] = list(self.if_stack)
                elif node.func.attr == "write":
                    for arg in node.args:
                        if "close_date" in ast.unparse(arg):
                            actions["has_close_date"] = True
            self.generic_visit(node)

        def visit_Assign(self, node):
            assign_str = ast.unparse(node)
            if "kanban_state" in assign_str:
                actions["has_kanban_reset"] = True
            elif "close_date" in assign_str:
                actions["has_close_date"] = True
            self.generic_visit(node)

    Visitor().visit(tree)
    return actions


def format_stage_workflow_note(model_name: str, actions: dict) -> str:
    """Format a deterministic factual block describing stage-driven workflow actions in write()."""
    if not actions.get("has_recurrence_copy") and not actions.get("has_close_date"):
        return ""

    header = "[FAIT DÉTERMINISTIQUE -- WORKFLOW D'ÉTAPE ET RÉCURRENCE (write())]"
    lines = [
        header,
        f"Pour le modèle '{model_name}', le passage à une étape terminée (stage_id où done=True) déclenche automatiquement dans write() :",
    ]

    if actions.get("has_recurrence_copy"):
        lines.append(
            "1. Condition de duplication / récurrence : une nouvelle demande est créée par duplication (copy()) "
            "uniquement si la maintenance est préventive et récurrente, ET si repeat_type == 'forever' ou que la "
            "nouvelle date calculée reste inférieure ou égale à la date limite repeat_until (schedule_date <= repeat_until)."
        )
        lines.append(
            "2. Paramètres de la nouvelle occurrence : calcul de la nouvelle date (schedule_date actuelle/existante + "
            "repeat_interval en repeat_unit) et réinsertion à l'étape par défaut (_default_stage)."
        )

    effects = []
    if actions.get("has_close_date"):
        effects.append("enregistrement de la date de fin (close_date = today)")
    if actions.get("has_kanban_reset"):
        effects.append("réinitialisation de kanban_state à 'normal'")
    if actions.get("has_activity_update"):
        effects.append("mise à jour et replanification des activités (activity_feedback et activity_update)")

    if effects:
        lines.append(f"3. Mise à jour de la demande terminée : {', '.join(effects)}.")

    lines.append(
        "(Note importante : le passage à 'done' n'ajoute ni ne notifie aucun follower ; "
        "_add_followers n'intervient que si le créateur ou le technicien change.)"
    )
    return "\n".join(lines)
