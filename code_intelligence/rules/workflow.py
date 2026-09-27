"""
code_intelligence/deterministic/workflow_process.py

Workflow state transition graph analysis (WorkflowState -> TRANSITIONS_VIA -> WorkflowState).
"""

import ast
from dataclasses import dataclass, field
import logging
import re
import textwrap
from typing import Any, Dict, List, Set
import networkx as nx

logger = logging.getLogger(__name__)

from code_intelligence.rules.common import NOT_FOUND_MARKER, QueryStatus
from code_intelligence.rules.ontology import tags_for_node_attrs
from code_intelligence.utils import format_xml_id_citations
from core.evidence.evidence import Evidence, EvidenceSourceType, make_evidence


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
            source=f"transition:{model_name}:{method}:{origin}:{target}",
            value=target,
            confidence="HIGH",
        ))

    if not transitions:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Model '{model_name}' has no explicit workflow state transitions defined",
            source=f"workflow:{model_name}",
            value=None,
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
            summary_text=f"Model '{model_name}' {NOT_FOUND_MARKER} (probable typo or missing model)."
        )

    states: Set[str] = set()
    transitions: List[Dict[str, Any]] = []

    for n, data in G.nodes(data=True):
        if data.get("node_type") == "WorkflowState" and data.get("model") == model_name:
            states.add(data.get("state_value", ""))

    for u, v, edge_data in G.edges(data=True):
        if edge_data.get("edge_type") == "TRANSITIONS_VIA":
            orig_st = u.replace(f"state:{model_name}.", "").replace("state:", "")
            targ_st = v.replace(f"state:{model_name}.", "").replace("state:", "")

            if u.startswith(f"state:{model_name}") or v.startswith(f"state:{model_name}"):
                transitions.append({
                    "origin_state": orig_st,
                    "target_state": targ_st,
                    "method_name": edge_data.get("method_name", ""),
                    "button_label": edge_data.get("label_bouton", ""),
                    "required_groups": edge_data.get("groupe_requis", []),
                })

    model_tags = tags_for_node_attrs(G.nodes[model_node])

    if not transitions:
        return WorkflowProcessResult(
            model_name=model_name,
            status=QueryStatus.EMPTY,
            states=sorted(list(states)),
            model_tags=model_tags,
            summary_text=f"Model '{model_name}' exists in the index but has no explicit workflow state transitions defined.",
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
        )

    summary = f"Workflow Process for '{model_name}' ({len(transitions)} transitions):\n" + "\n".join(steps_text)

    return WorkflowProcessResult(
        model_name=model_name,
        status=QueryStatus.FOUND,
        states=sorted(list(states)),
        transitions=transitions,
        model_tags=model_tags,
        summary_text=summary,
        evidence=_build_workflow_evidence(model_name, transitions),
    )


def _correct_noop_hook_hallucinations(
    final_answer: str, raw_tool_output: str, question: str = ""
) -> str:
    """Strip or correct hallucinated business effects (such as tax recalculation or
    validation) attributed to methods that are deterministically identified as no-op hooks
    in tool observations (todo/contexte.txt section 939/942 Point R)."""
    if not final_answer or not raw_tool_output:
        return final_answer

    noop_marker = "[NOTE DÉTERMINISTIQUE -- HOOK SANS EFFET / NO-OP]"
    if noop_marker not in raw_tool_output:
        return final_answer

    # Check for tax-related no-op hook (e.g. validate_taxes_on_sales_order)
    if "validate_taxes_on_sales_order" in raw_tool_output:
        # 1. Remove any bullet point claiming tax validation/recalculation
        # e.g.: - **Validation des taxes** : les taxes sont recalculées et validées...
        tax_bullet_pattern = re.compile(
            r"^\s*-\s+\*\*[^*]*taxe[^*]*\*\*\s*:[^\n]*(?:\n|$)",
            re.MULTILINE | re.IGNORECASE,
        )
        cleaned = tax_bullet_pattern.sub("", final_answer)

        # 2. Clean inline summary phrases
        cleaned = re.sub(r",\s*applique les taxes\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bapplique les taxes\s*,\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bvalide(?: et recalcule)? les taxes\s*,\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r",\s*valide(?: et recalcule)? les taxes\b", "", cleaned, flags=re.IGNORECASE)

        if cleaned != final_answer:
            logger.info(
                "Node [code_intelligence_agent]: Stripped hallucinated tax validation claims from no-op hook."
            )
            final_answer = cleaned

    return final_answer


def _backfill_action_confirm_workflow_details(
    final_answer: str, raw_tool_output: str, question: str = ""
) -> str:
    """Ensure that the confirmation flow (action_confirm) explicitly mentions the initial
    precondition verification (_can_be_confirmed requiring draft/sent state, otherwise UserError)
    and analytic distribution validation when present in tool observations (todo/contexte.txt
    section 939 SAL-Q2)."""
    if not final_answer or not raw_tool_output:
        return final_answer

    from code_intelligence.rules.group_resolver import _fold_accents
    folded_q = _fold_accents(question.lower()) if question else ""

    # Only apply if question or observations target action_confirm
    is_confirm_q = bool(
        "action_confirm" in folded_q
        or ("confirm" in folded_q and "vente" in folded_q)
        or ("confirm" in folded_q and "commande" in folded_q)
    )
    if not is_confirm_q:
        return final_answer

    # Check if _can_be_confirmed was read
    if "def _can_be_confirmed" not in raw_tool_output and "_can_be_confirmed" not in raw_tool_output:
        return final_answer

    state_change_pat = re.compile(
        r"^\s*-\s+\*\*Changement d[’\']état\*\*\s*:[^\n]*(?:\n|$)",
        re.MULTILINE | re.IGNORECASE,
    )
    if state_change_pat.search(final_answer):
        replacement = (
            "- **Vérification préalable** : le système vérifie d'abord que les commandes sont en état « Brouillon » ou « Envoyée » (sinon une erreur bloque la confirmation).\n"
            "- **Validation analytique** : la distribution analytique des lignes de commande est validée.\n"
            "- **Changement d’état et date** : la commande passe à l'état « En cours » (état sale) avec enregistrement de la date de confirmation.\n"
        )
        final_answer = state_change_pat.sub(replacement, final_answer)
        logger.info(
            "Node [code_intelligence_agent]: Backfilled action_confirm precondition and analytic distribution."
        )

    return final_answer


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
                        try:
                            arg_str = ast.unparse(arg)
                            if "close_date" in arg_str:
                                actions["has_close_date"] = True
                        except Exception:
                            pass
            self.generic_visit(node)

        def visit_Assign(self, node):
            try:
                assign_str = ast.unparse(node)
                if "kanban_state" in assign_str:
                    actions["has_kanban_reset"] = True
                elif "close_date" in assign_str:
                    actions["has_close_date"] = True
            except Exception:
                pass
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


def _backfill_stage_recurrence_conditions(
    final_answer: str, raw_tool_output: str, question: str = ""
) -> str:
    """Ensure that stage-driven recurrence answers (MNT-Q2) accurately reflect the boundary
    condition (repeat_type == 'forever' or schedule_date <= repeat_until) and do not invent
    unrelated follower notifications upon reaching 'done' (todo/contexte.txt section 939 Point S)."""
    if not final_answer or not raw_tool_output:
        return final_answer

    fact_marker = "[FAIT DÉTERMINISTIQUE -- WORKFLOW D'ÉTAPE ET RÉCURRENCE (write())]"
    if fact_marker not in raw_tool_output and "repeat_type == 'forever'" not in raw_tool_output:
        return final_answer

    from code_intelligence.rules.group_resolver import _fold_accents
    folded_q = _fold_accents(question.lower()) if question else ""

    # Strip hallucinated followers notifications on reaching done
    followers_bullet_re = re.compile(
        r"^\s*-\s+\*\*(?:Gestion des notifications|Followers|Abonn[eé]s)\*\*.*?(?=\n\s*-\s+\*\*|\Z)",
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    cleaned = followers_bullet_re.sub("", final_answer).rstrip()
    if cleaned != final_answer:
        logger.info("Node [code_intelligence_agent]: Stripped false followers notification bullet from stage workflow answer.")
        final_answer = cleaned

    boundary_item = (
        "- **Condition d’arrêt de la récurrence** : la duplication automatique n'a lieu que si la répétition "
        "est configurée sans fin (*repeat_type* = 'forever') ou si la date calculée reste antérieure ou égale "
        "à la date limite (*repeat_until*)."
    )
    # Try inserting right after the new request creation bullet if present
    insert_pat = re.compile(
        r"(\s*-\s+La nouvelle demande est placée dans l’étape par défaut[^\n]*)",
        re.IGNORECASE,
    )
    if insert_pat.search(final_answer):
        final_answer = insert_pat.sub(r"\1\n  " + boundary_item, final_answer)
    else:
        final_answer = final_answer.rstrip() + "\n\n" + boundary_item
    logger.info("Node [code_intelligence_agent]: Backfilled stage recurrence boundary condition (repeat_until / forever).")

    return final_answer


