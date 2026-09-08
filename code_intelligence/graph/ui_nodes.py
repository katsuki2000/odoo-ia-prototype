"""
code_intelligence/graph/ui_nodes.py

Sub-graph node and edge builders for menus, workflows, and form buttons.
"""

from typing import Dict
import networkx as nx

from code_intelligence.semantic_tags import BehavioralTag
from code_intelligence.utils import resolve_model_xmlref
from .models import ParsedModule, ResolvedSymbolRegistry


def add_menu_nodes(
    G: nx.DiGraph,
    registry: ResolvedSymbolRegistry,
    modules_dict: Dict[str, ParsedModule],
):
    """Add Menu nodes as fuzzy-matching targets and link to models via actions."""
    for mod_name, mod in modules_dict.items():
        for menu in mod.menuitems:
            full_xml_id = menu.xml_id if "." in menu.xml_id else f"{mod_name}.{menu.xml_id}"
            menu_node_id = f"menu:{full_xml_id}"

            G.add_node(
                menu_node_id,
                node_type="Menu",
                xml_id=full_xml_id,
                name=menu.name,
                sequence=menu.sequence,
                filepath=menu.filepath,
                action_ref=menu.action or "",
                groups=[(g if "." in g else f"{mod_name}.{g}") for g in menu.groups],
                behavioral_tags=[],
                technical_tags=[],
            )

            for g in menu.groups:
                group_full = g if "." in g else f"{mod_name}.{g}"
                G.add_edge(menu_node_id, f"group:{group_full}", edge_type="APPLIES_TO_GROUP")

            if menu.parent:
                parent_full = menu.parent if "." in menu.parent else f"{mod_name}.{menu.parent}"
                G.add_edge(menu_node_id, f"menu:{parent_full}", edge_type="CHILD_OF")

            if not menu.action:
                continue

            action_ref = menu.action if "." in menu.action else f"{mod_name}.{menu.action}"

            action_rec = registry.actions.get(action_ref) or registry.actions.get(menu.action)
            target_model = action_rec.res_model if (action_rec and action_rec.res_model) else None
            via = "act_window" if target_model else None

            if not target_model:
                sa_rec = registry.server_actions.get(action_ref) or registry.server_actions.get(menu.action)
                if sa_rec and sa_rec.model_id:
                    target_model = resolve_model_xmlref(sa_rec.model_id)
                    via = "server_action"

            if target_model:
                model_node_id = f"model:{target_model}"
                G.add_edge(menu_node_id, model_node_id, edge_type="OPENS_MODEL", via=via)
                if model_node_id in G:
                    G.nodes[menu_node_id]["behavioral_tags"] = list(
                        G.nodes[model_node_id].get("behavioral_tags", [])
                    )
                    G.nodes[menu_node_id]["technical_tags"] = list(
                        G.nodes[model_node_id].get("technical_tags", [])
                    )


def add_workflow_nodes_and_edges(
    G: nx.DiGraph,
    registry: ResolvedSymbolRegistry,
    modules_dict: Dict[str, ParsedModule],
):
    """Build Workflow Sub-Graph with WorkflowState nodes and TRANSITIONS_VIA edges."""
    for model_name, decls in registry.models.items():
        state_field = None
        for d in decls:
            for f in d.fields:
                if f.name == "state":
                    state_field = f
                    break
            if state_field:
                break

        if not state_field:
            continue

        form_buttons = []
        for mod in modules_dict.values():
            for view in mod.views:
                if view.model == model_name:
                    form_buttons.extend(view.buttons)

        common_states = ["draft", "sent", "sale", "done", "cancel", "confirm", "validate"]
        for st in common_states:
            state_node_id = f"state:{model_name}.{st}"
            G.add_node(
                state_node_id,
                node_type="WorkflowState",
                model=model_name,
                state_value=st,
                behavioral_tags=[BehavioralTag.WORKFLOW_RULE.value],
                technical_tags=[],
            )

        for btn in form_buttons:
            if not btn.states or not btn.name:
                continue

            origin_states = [s.strip() for s in btn.states.split(",") if s.strip()]
            target_st = "sale" if "confirm" in btn.name else ("cancel" if "cancel" in btn.name else "done")

            for orig in origin_states:
                orig_node_id = f"state:{model_name}.{orig}"
                target_node_id = f"state:{model_name}.{target_st}"

                G.add_edge(
                    orig_node_id,
                    target_node_id,
                    edge_type="TRANSITIONS_VIA",
                    method_name=btn.name,
                    label_bouton=btn.string,
                    groupe_requis=btn.groups,
                )


def add_view_button_nodes_and_edges(
    G: nx.DiGraph,
    modules_dict: Dict[str, ParsedModule],
):
    """Extract form view buttons and index them as Button nodes and HAS_BUTTON edges."""
    for mod in modules_dict.values():
        for view in mod.views:
            model_name = view.model
            if not model_name:
                continue
            model_node_id = f"model:{model_name}"
            for btn in view.buttons:
                if not btn.name:
                    continue
                button_node_id = f"button:{model_name}.{btn.name}"
                if not G.has_node(button_node_id):
                    G.add_node(
                        button_node_id,
                        node_type="Button",
                        name=btn.name,
                        label=btn.string,
                        groups=btn.groups,
                        invisible=btn.invisible,
                        model=model_name,
                    )
                if G.has_node(model_node_id):
                    G.add_edge(
                        model_node_id,
                        button_node_id,
                        edge_type="HAS_BUTTON",
                        method_name=btn.name,
                        label_bouton=btn.string,
                        groupe_requis=btn.groups,
                        invisible=btn.invisible,
                    )


__all__ = [
    "add_menu_nodes",
    "add_workflow_nodes_and_edges",
    "add_view_button_nodes_and_edges",
]
