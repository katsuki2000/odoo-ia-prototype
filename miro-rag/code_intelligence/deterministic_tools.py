"""
code_intelligence/deterministic_tools.py

Specialized Deterministic Graph Query Tools for Odoo Code Intelligence.
Implements Epic B:
  - Story B1.1: qui_a_acces_a(model, droit, group_id=None)
  - Story B1.2: impact_changement_champ(field_name, model)
  - Story B1.3: chemin_execution_bouton(button_label_or_name, model)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Any
import logging

import networkx as nx

_logger = logging.getLogger(__name__)


@dataclass
class RuleDetail:
    rule_xml_id: str
    rule_name: str
    domain_force: str
    groups: List[str]


@dataclass
class AccessEvaluationResult:
    model_name: str
    droit_demande: str
    allowed_groups: List[str] = field(default_factory=list)
    all_authenticated_access: bool = False
    active_rules: List[RuleDetail] = field(default_factory=list)
    client_side_checks: List[Dict[str, Any]] = field(default_factory=list)
    summary_text: str = ""


def qui_a_acces_a(
    G: nx.DiGraph,
    model_name: str,
    droit: str = "read",
    group_id: Optional[str] = None
) -> AccessEvaluationResult:
    """
    Story B1.1: Evaluates access rights for a given model and permission type.
    Combines CSV ACLs, ir.rule domain_force expressions, res.groups implied hierarchy, and JS client checks.
    """
    model_node = f"model:{model_name}"
    
    # Normalize droit parameter
    perm_attr = f"perm_{droit}" if droit in {"read", "write", "create", "unlink"} else "perm_read"

    if model_node not in G:
        return AccessEvaluationResult(
            model_name=model_name,
            droit_demande=droit,
            summary_text=f"Model '{model_name}' was not found in the indexed knowledge graph."
        )

    allowed_groups: Set[str] = set()
    all_authenticated = False
    active_rules: List[RuleDetail] = []
    client_checks: List[Dict[str, Any]] = []

    # 1. Traversal: Model -> GRANTED_BY -> AccessEntry -> APPLIES_TO_GROUP -> Group
    for neighbor in G.neighbors(model_node):
        edge_data = G.get_edge_data(model_node, neighbor) or {}
        edge_type = edge_data.get("edge_type")

        # Process ACLs
        if edge_type == "GRANTED_BY" and G.nodes[neighbor].get("node_type") == "AccessEntry":
            acl_node = G.nodes[neighbor]
            if acl_node.get(perm_attr, False):
                if acl_node.get("all_authenticated", False):
                    all_authenticated = True
                
                # Get groups attached to this ACL
                for acl_neighbor in G.neighbors(neighbor):
                    acl_edge = G.get_edge_data(neighbor, acl_neighbor) or {}
                    if acl_edge.get("edge_type") == "APPLIES_TO_GROUP":
                        grp_xml_id = acl_neighbor.replace("group:", "")
                        allowed_groups.add(grp_xml_id)

                        # Expand group hierarchy via reverse IMPLIES edges (child groups that inherit this group)
                        _expand_inheriting_groups(G, grp_xml_id, allowed_groups)

        # Process Record Rules
        elif edge_type == "RESTRICTED_BY" and G.nodes[neighbor].get("node_type") == "Rule":
            rule_node = G.nodes[neighbor]
            if rule_node.get(perm_attr, True): # Default True for rules if perm flag is active
                rule_groups = []
                for rule_neighbor in G.neighbors(neighbor):
                    rule_edge = G.get_edge_data(neighbor, rule_neighbor) or {}
                    if rule_edge.get("edge_type") == "APPLIES_TO_GROUP":
                        grp_xml_id = rule_neighbor.replace("group:", "")
                        rule_groups.append(grp_xml_id)

                active_rules.append(
                    RuleDetail(
                        rule_xml_id=rule_node.get("xml_id", neighbor.replace("rule:", "")),
                        rule_name=rule_node.get("name", ""),
                        domain_force=rule_node.get("domain_force", ""),
                        groups=rule_groups,
                    )
                )

    # 2. Filter by specific group_id if requested
    if group_id:
        has_access = all_authenticated or (group_id in allowed_groups)
        summary = (
            f"Group '{group_id}' HAS {droit.upper()} access to '{model_name}'."
            if has_access
            else f"Group '{group_id}' DOES NOT HAVE {droit.upper()} access to '{model_name}'."
        )
    else:
        if all_authenticated:
            grp_str = "All authenticated users"
        elif allowed_groups:
            grp_str = ", ".join(sorted(allowed_groups))
        else:
            grp_str = "No groups explicitly granted"

        summary = f"Model '{model_name}' [{droit.upper()}]: Granted to {grp_str}. Active Rules: {len(active_rules)}."

    return AccessEvaluationResult(
        model_name=model_name,
        droit_demande=droit,
        allowed_groups=sorted(list(allowed_groups)),
        all_authenticated_access=all_authenticated,
        active_rules=active_rules,
        client_side_checks=client_checks,
        summary_text=summary,
    )


@dataclass
class FieldImpactResult:
    field_name: str
    model_name: str
    upstream_triggers: List[str] = field(default_factory=list)
    downstream_computed_fields: List[str] = field(default_factory=list)
    relational_target: Optional[str] = None
    compute_method: Optional[str] = None
    summary_text: str = ""


def impact_changement_champ(
    G: nx.DiGraph,
    field_name: str,
    model_name: str
) -> FieldImpactResult:
    """
    Story B1.2: Analyzes upstream dependencies and downstream impact of modifying a field.
    Traces COMPUTED_BY, DEPENDS_ON, and RELATES_TO edges on the Knowledge Graph.
    """
    field_node = f"field:{model_name}.{field_name}"

    if field_node not in G:
        return FieldImpactResult(
            field_name=field_name,
            model_name=model_name,
            summary_text=f"Field '{field_name}' on model '{model_name}' was not found in the indexed knowledge graph."
        )

    f_data = G.nodes[field_node]
    compute_method = f_data.get("compute")
    relational_target = f_data.get("comodel_name")

    upstream_triggers: Set[str] = set()
    downstream_computed_fields: Set[str] = set()

    # 1. Upstream Traversal: field -> COMPUTED_BY -> method -> DEPENDS_ON -> trigger_field
    for neighbor in G.neighbors(field_node):
        edge_data = G.get_edge_data(field_node, neighbor) or {}
        if edge_data.get("edge_type") == "COMPUTED_BY":
            # Method node
            method_node = neighbor
            for method_neighbor in G.neighbors(method_node):
                m_edge = G.get_edge_data(method_node, method_neighbor) or {}
                if m_edge.get("edge_type") == "DEPENDS_ON":
                    trig_field_name = method_neighbor.replace(f"field:{model_name}.", "")
                    upstream_triggers.add(trig_field_name)

    # 2. Downstream Traversal: method -> DEPENDS_ON -> field_node (in_edges of field_node)
    for in_node, _, in_edge_data in G.in_edges(field_node, data=True):
        if in_edge_data.get("edge_type") == "DEPENDS_ON":
            # in_node is a method that depends on this field
            method_node = in_node
            # Find computed fields attached to this method (in_edges of method_node with COMPUTED_BY)
            for comp_node, _, comp_edge_data in G.in_edges(method_node, data=True):
                if comp_edge_data.get("edge_type") == "COMPUTED_BY":
                    impacted_field_name = comp_node.replace(f"field:{model_name}.", "").replace("field:", "")
                    downstream_computed_fields.add(impacted_field_name)

    # Build summary
    downstream_str = ", ".join(sorted(downstream_computed_fields)) if downstream_computed_fields else "None"
    upstream_str = ", ".join(sorted(upstream_triggers)) if upstream_triggers else "None"

    summary = (
        f"Field '{field_name}' on '{model_name}': "
        f"Triggers recomputation of [{downstream_str}]. "
        f"Depends on [{upstream_str}]."
    )

    return FieldImpactResult(
        field_name=field_name,
        model_name=model_name,
        upstream_triggers=sorted(list(upstream_triggers)),
        downstream_computed_fields=sorted(list(downstream_computed_fields)),
        relational_target=relational_target,
        compute_method=compute_method,
        summary_text=summary,
    )


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


def chemin_execution_bouton(
    G: nx.DiGraph,
    button_label_or_name: str,
    model_name: str
) -> ButtonExecutionPathResult:
    """
    Story B1.3: Traces step-by-step workflow execution path for a UI button click.
    Combines UI View Button -> Python Method -> Workflow State Transition -> Security Rules.
    """
    model_node = f"model:{model_name}"

    if model_node not in G:
        return ButtonExecutionPathResult(
            button_identifier=button_label_or_name,
            model_name=model_name,
            summary_text=f"Model '{model_name}' was not found in the indexed knowledge graph."
        )

    # Search for TRANSITIONS_VIA edges linked to this model
    method_name = ""
    origin_states: Set[str] = set()
    target_state = ""
    required_groups: Set[str] = set()
    execution_steps: List[str] = []

    # Search workflow transition edges
    for u, v, edge_data in G.edges(data=True):
        if edge_data.get("edge_type") == "TRANSITIONS_VIA":
            m_name = edge_data.get("method_name", "")
            btn_label = edge_data.get("label_bouton", "")

            # Match button by method name or label
            if (
                button_label_or_name.lower() in m_name.lower()
                or button_label_or_name.lower() in btn_label.lower()
                or m_name.lower() in button_label_or_name.lower()
            ):
                method_name = m_name
                orig_st = u.replace(f"state:{model_name}.", "").replace("state:", "")
                targ_st = v.replace(f"state:{model_name}.", "").replace("state:", "")

                origin_states.add(orig_st)
                target_state = targ_st

                groups_req = edge_data.get("groupe_requis", [])
                if isinstance(groups_req, list):
                    required_groups.update(groups_req)

    # If method_name not found via workflow edges, search direct method nodes
    if not method_name:
        method_name = button_label_or_name if button_label_or_name.startswith("action_") or button_label_or_name.startswith("_") else f"action_{button_label_or_name.lower()}"

    method_node_id = f"method:{model_name}.{method_name}"
    method_exists = method_node_id in G

    # Build execution steps
    execution_steps.append(f"1. UI Click: User clicks button '{button_label_or_name}' on form view of '{model_name}'.")
    execution_steps.append(f"2. Method Invocation: Calls Python method '{method_name}()' (Defined: {method_exists}).")

    if origin_states and target_state:
        orig_str = ", ".join(sorted(origin_states))
        execution_steps.append(f"3. State Transition: Transitions model '{model_name}' state from [{orig_str}] -> '{target_state}'.")
    else:
        execution_steps.append(f"3. State Transition: Executes method logic without state machine transition.")

    if required_groups:
        grp_str = ", ".join(sorted(required_groups))
        execution_steps.append(f"4. Security Requirement: Button restricted to groups [{grp_str}].")
    else:
        execution_steps.append(f"4. Security Requirement: No button-level group restriction specified.")

    summary = (
        f"Button '{button_label_or_name}' on '{model_name}': "
        f"Calls '{method_name}()'. "
        f"Transition: [{', '.join(sorted(origin_states))}] -> '{target_state}'. "
        f"Required Groups: [{', '.join(sorted(required_groups)) if required_groups else 'None'}]."
    )

    return ButtonExecutionPathResult(
        button_identifier=button_label_or_name,
        model_name=model_name,
        method_name=method_name,
        origin_states=sorted(list(origin_states)),
        target_state=target_state,
        required_groups=sorted(list(required_groups)),
        execution_steps=execution_steps,
        summary_text=summary,
    )


def _expand_inheriting_groups(G: nx.DiGraph, parent_group: str, allowed_groups: Set[str]):
    """Recursively find all child groups that inherit parent_group via IMPLIES edges."""
    parent_node = f"group:{parent_group}"
    if parent_node not in G:
        return

    # In DiGraph, if Child IMPLIES Parent, edge is Child -> Parent (in_edges of Parent)
    for child_node, _, edge_data in G.in_edges(parent_node, data=True):
        if edge_data.get("edge_type") == "IMPLIES":
            child_group_id = child_node.replace("group:", "")
            if child_group_id not in allowed_groups:
                allowed_groups.add(child_group_id)
                _expand_inheriting_groups(G, child_group_id, allowed_groups)
