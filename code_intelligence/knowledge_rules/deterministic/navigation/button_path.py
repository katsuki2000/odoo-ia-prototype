"""
code_intelligence/deterministic/button_path.py

Tracing execution paths for Odoo UI buttons, menu items, and workflow transitions.
"""

from typing import List, Optional, Set
import networkx as nx

from code_intelligence.knowledge_rules.deterministic.navigation.button_path_models import (
    ButtonExecutionPathResult,
    _build_button_execution_evidence,
)
from code_intelligence.knowledge_rules.deterministic.common import NOT_FOUND_MARKER
from code_intelligence.knowledge_rules.deterministic.access.group_resolver import (
    _expand_implied_user_groups,
    resolve_group_identifier,
)
from code_intelligence.knowledge_rules.deterministic.navigation.menu_view_finder import search_dynamic_view_or_menus
from code_intelligence.knowledge_rules.deterministic.navigation.xml_view_finder import _find_field_in_xml_views
from code_intelligence.knowledge_rules.ontology.query import tags_for_node_attrs
from code_intelligence.utils import format_file_link, format_xml_id_citations


def _requester_satisfies_required_groups(
    G: nx.DiGraph, required_groups: List[str], user_groups: List[str]
) -> bool:
    """
    True if the demandeur belongs to at least one of required_groups (Odoo
    button-level groups="..." is an OR condition across the listed groups).
    """
    if not required_groups:
        return True
    if not user_groups:
        return False

    user_group_set: Set[str] = set(user_groups)
    for g in list(user_group_set):
        _expand_implied_user_groups(G, g, user_group_set)

    return any(
        resolve_group_identifier(G, ug, required_groups) is not None
        for ug in user_group_set
    )


def button_execution_path(
    G: nx.DiGraph,
    button_label_or_name: str,
    model_name: str,
    user_groups: Optional[List[str]] = None,
) -> ButtonExecutionPathResult:
    """
    Traces step-by-step workflow execution path for a UI button click or UI field inspection.
    Combines UI View Button/Field -> Python Method -> Workflow State Transition -> Security Rules.
    """
    model_node = f"model:{model_name}"

    if model_node not in G:
        return ButtonExecutionPathResult(
            button_identifier=button_label_or_name,
            model_name=model_name,
            summary_text=f"Model '{model_name}' {NOT_FOUND_MARKER}."
        )

    method_name = ""
    origin_states: Set[str] = set()
    target_state = ""
    required_groups: Set[str] = set()
    execution_steps: List[str] = []

    candidate_transitions = []
    target_clean = button_label_or_name.strip().lower()
    for u, v, edge_data in G.edges(data=True):
        if edge_data.get("edge_type") == "TRANSITIONS_VIA":
            state_val = u.replace("state:", "")
            if "." in state_val:
                edge_model = state_val.rsplit(".", 1)[0]
                if edge_model != model_name:
                    continue

            m_name = (edge_data.get("method_name") or "").strip()
            btn_label = (edge_data.get("label_bouton") or "").strip()
            m_lower = m_name.lower()
            lbl_lower = btn_label.lower()

            score = 0
            if target_clean == m_lower or (lbl_lower and target_clean == lbl_lower):
                score = 3
            elif (lbl_lower and target_clean in lbl_lower) or (m_lower and target_clean in m_lower):
                score = 2
            elif (m_lower and m_lower in target_clean) or (lbl_lower and lbl_lower in target_clean):
                score = 1

            if score > 0:
                candidate_transitions.append((score, m_name, u, v, edge_data))

    if candidate_transitions:
        max_score = max(c[0] for c in candidate_transitions)
        best_candidates = [c for c in candidate_transitions if c[0] == max_score]
        chosen_method = best_candidates[0][1]
        for score, m_name, u, v, edge_data in best_candidates:
            if m_name == chosen_method:
                method_name = m_name
                orig_st = u.replace(f"state:{model_name}.", "").replace("state:", "")
                targ_st = v.replace(f"state:{model_name}.", "").replace("state:", "")
                origin_states.add(orig_st)
                target_state = targ_st
                groups_req = edge_data.get("groupe_requis", [])
                if isinstance(groups_req, list):
                    required_groups.update(groups_req)

    invisible_condition = ""
    if not method_name:
        model_node_id = f"model:{model_name}"
        if model_node_id in G:
            candidate_buttons = []
            for _, _, edge_data in G.out_edges(model_node_id, data=True):
                if edge_data.get("edge_type") == "HAS_BUTTON":
                    m_name = (edge_data.get("method_name") or "").strip()
                    btn_label = (edge_data.get("label_bouton") or "").strip()
                    m_lower = m_name.lower()
                    lbl_lower = btn_label.lower()
                    score = 0
                    if target_clean == m_lower or (lbl_lower and target_clean == lbl_lower):
                        score = 3
                    elif (lbl_lower and target_clean in lbl_lower) or (m_lower and target_clean in m_lower):
                        score = 2
                    elif (m_lower and m_lower in target_clean) or (lbl_lower and lbl_lower in target_clean):
                        score = 1
                    if score > 0:
                        candidate_buttons.append((score, m_name, edge_data))
            if candidate_buttons:
                candidate_buttons.sort(key=lambda x: x[0], reverse=True)
                _, method_name, edge_data = candidate_buttons[0]
                groups_req = edge_data.get("groupe_requis", [])
                if isinstance(groups_req, list):
                    required_groups.update(groups_req)
                invisible_condition = edge_data.get("invisible", "")

    if not method_name:
        field_view_res = _find_field_in_xml_views(G, model_name, button_label_or_name, user_groups=user_groups)
        if field_view_res is not None:
            return field_view_res

    if not method_name:
        method_name = button_label_or_name if button_label_or_name.startswith("action_") or button_label_or_name.startswith("_") else f"action_{button_label_or_name.lower()}"

    method_node_id = f"method:{model_name}.{method_name}"
    method_exists = method_node_id in G
    method_tags = tags_for_node_attrs(G.nodes[method_node_id]) if method_exists else []

    if not method_exists and not origin_states and not invisible_condition:
        dyn_or_menu = search_dynamic_view_or_menus(G, model_name, button_label_or_name)
        if dyn_or_menu is not None:
            return dyn_or_menu

    if not method_exists and not origin_states and not invisible_condition:
        execution_steps.append(f"1. UI Search: Button or UI element '{button_label_or_name}' was not found in XML views for '{model_name}'.")
        execution_steps.append(f"2. Method Lookup: Candidate method '{method_name}()' is not defined on model '{model_name}'.")
        execution_steps.append("3. State Transition: None.")
        execution_steps.append("4. Security Requirement: None.")
        summary = (
            f"Button or UI element '{button_label_or_name}' on '{model_name}': "
            f"Neither button declaration nor method '{method_name}()' found in knowledge graph. "
            f"Transition: [] -> ''. "
            f"Required Groups: [None]."
        )
    else:
        method_link_str = f"Defined: {method_exists}"
        if method_exists and method_node_id in G:
            m_node = G.nodes[method_node_id]
            m_fp = m_node.get("filepath", "")
            m_line = m_node.get("lineno", 0)
            m_sites = m_node.get("override_sites") or []
            m_end = m_sites[0].get("end_lineno", m_line + 30) if m_sites else (m_line + 30)
            if m_fp:
                m_link = format_file_link(m_fp, m_line, m_end)
                method_link_str = f"Defined at {m_link}"
        execution_steps.append(f"1. UI Click: User clicks button '{button_label_or_name}' on form view of '{model_name}'.")
        execution_steps.append(f"2. Method Invocation: Calls Python method '{method_name}()' ({method_link_str}).")

        if origin_states and target_state:
            orig_str = ", ".join(sorted(origin_states))
            execution_steps.append(f"3. State Transition: Transitions model '{model_name}' state from [{orig_str}] -> '{target_state}'.")
        else:
            execution_steps.append(f"3. State Transition: Executes method logic without state machine transition.")

        if required_groups:
            grp_str = ", ".join(sorted(required_groups))
            _req_citations = format_xml_id_citations(sorted(required_groups))
            execution_steps.append(f"4. Security Requirement: Button restricted to groups [{grp_str}]. ({_req_citations})")
        else:
            execution_steps.append(f"4. Security Requirement: No button-level group restriction specified.")

        if invisible_condition:
            execution_steps.append(f"5. Visibility Condition: Button invisible condition '{invisible_condition}'.")

        summary = (
            f"Button '{button_label_or_name}' on '{model_name}': "
            f"Calls '{method_name}()' ({method_link_str}). "
            f"Transition: [{', '.join(sorted(origin_states))}] -> '{target_state}'. "
            f"Required Groups: [{', '.join(sorted(required_groups)) if required_groups else 'None'}]."
        )
        if invisible_condition:
            summary += f" Visibility: invisible='{invisible_condition}'."

    available_to_requester: Optional[bool] = None
    unavailable_reason = ""
    if user_groups is not None:
        available_to_requester = _requester_satisfies_required_groups(G, sorted(required_groups), user_groups)
        if not available_to_requester:
            unavailable_reason = (
                f"Ce bouton est restreint aux groupes [{', '.join(sorted(required_groups))}], "
                "dont le demandeur ne fait partie d'aucun -- l'action n'est pas disponible "
                "pour lui dans l'interface (bouton absent ou grise), pas seulement documentee "
                "comme restreinte."
            )
            summary += f" NON DISPONIBLE POUR LE DEMANDEUR : {unavailable_reason}"
            execution_steps.append(
                f"5. Disponibilite reelle : NON -- {unavailable_reason}"
            )
        else:
            execution_steps.append(
                "5. Disponibilite reelle : OUI -- le demandeur appartient a un groupe requis "
                "(ou aucun groupe n'est requis)."
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
        available_to_requester=available_to_requester,
        unavailable_reason=unavailable_reason,
        method_tags=method_tags,
        evidence=_build_button_execution_evidence(
            button_label_or_name, model_name, method_name, method_exists,
            origin_states, target_state, required_groups,
            user_groups, available_to_requester,
        ),
    )
