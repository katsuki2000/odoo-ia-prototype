"""
code_intelligence/graph/models.py

Data models and registries for cross-file Odoo symbol resolution and graph building.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from code_intelligence.extractor.manifest import OdooManifest
from code_intelligence.extractor.python import OdooModelDeclaration
from code_intelligence.extractor.xml import (
    OdooActionRecord,
    OdooBaseAutomationRecord,
    OdooGroupRecord,
    OdooMenuItemRecord,
    OdooRuleRecord,
    OdooServerActionRecord,
    OdooViewRecord,
)
from code_intelligence.extractor.csv import OdooAccessEntry


class UnresolvedCategory(Enum):
    ABSENT_FROM_CORPUS = "absent_from_corpus"
    CORE_ODOO_OUT_OF_SCOPE = "core_odoo_out_of_scope"
    PROBABLE_TYPO = "probable_typo"


@dataclass
class UnresolvedReference:
    source_module: str
    source_file: str
    symbol_ref: str
    ref_type: str  # "model", "group", "rule", "action"
    category: UnresolvedCategory
    detail: str = ""


@dataclass
class ParsedModule:
    manifest: Optional[OdooManifest]
    models: List[OdooModelDeclaration] = field(default_factory=list)
    rules: List[OdooRuleRecord] = field(default_factory=list)
    groups: List[OdooGroupRecord] = field(default_factory=list)
    actions: List[OdooActionRecord] = field(default_factory=list)
    server_actions: List[OdooServerActionRecord] = field(default_factory=list)
    base_automations: List[OdooBaseAutomationRecord] = field(default_factory=list)
    menuitems: List[OdooMenuItemRecord] = field(default_factory=list)
    views: List[OdooViewRecord] = field(default_factory=list)
    acl_entries: List[OdooAccessEntry] = field(default_factory=list)
    translations: List[object] = field(default_factory=list)


@dataclass
class ResolvedSymbolRegistry:
    # Key = model_name (e.g. "sale.order"), Value = List of declarations across modules
    models: Dict[str, List[OdooModelDeclaration]] = field(default_factory=dict)
    # Key = model_name, Value = List of module names matching models[model_name] order
    model_modules: Dict[str, List[str]] = field(default_factory=dict)
    # Key = full_xml_id (e.g. "base.group_user" or "sale.group_sale_manager"), Value = Record
    groups: Dict[str, OdooGroupRecord] = field(default_factory=dict)
    rules: Dict[str, OdooRuleRecord] = field(default_factory=dict)
    actions: Dict[str, OdooActionRecord] = field(default_factory=dict)
    server_actions: Dict[str, OdooServerActionRecord] = field(default_factory=dict)
    base_automations: Dict[str, OdooBaseAutomationRecord] = field(default_factory=dict)
    menuitems: Dict[str, OdooMenuItemRecord] = field(default_factory=dict)
    views: Dict[str, OdooViewRecord] = field(default_factory=dict)

    # Resolution & Unresolved tracking
    resolved_inheritance: Dict[str, List[str]] = field(default_factory=dict)  # model -> parent_models
    unresolved_references: List[UnresolvedReference] = field(default_factory=list)
    detected_cycles: List[List[str]] = field(default_factory=list)


CORE_BASE_MODULES = {
    "base", "mail", "portal", "utm", "bus", "web", "product", "account", "sale", "stock"
}


__all__ = [
    "UnresolvedCategory",
    "UnresolvedReference",
    "ParsedModule",
    "ResolvedSymbolRegistry",
    "CORE_BASE_MODULES",
]

# ── Security Group Nodes ──────────────────────────────────────────────────

"""
code_intelligence/graph/security_nodes.py

Sub-graph node and edge builders for security, rules, ACLs, server actions, and automations.
"""

from typing import Callable, Dict, Optional
import networkx as nx

from code_intelligence.rules.ontology import BehavioralTag, TechnicalTag
from code_intelligence.utils import resolve_model_xmlref


def add_security_group_nodes(
    G: nx.DiGraph,
    registry: ResolvedSymbolRegistry,
    modules_dict: Dict[str, ParsedModule],
    domain_force_references_state_fn: Callable[[Optional[str]], bool],
):
    """Add Group, Rule, AccessEntry, ServerAction, and AutomationRule nodes + security edges."""
    # 0. Collect implied_group declarations from res.config.settings fields
    #    (Section 925: detect feature-flag groups activated via Settings booleans)
    settings_implied_groups: Dict[str, str] = {}  # {group_xml_id: setting_field_name}
    for model_name, decl_list in registry.models.items():
        # res.config.settings or any model that _inherit it
        if model_name == "res.config.settings" or "res.config.settings" in sum(
            (d.inherit for d in decl_list), []
        ):
            for decl in decl_list:
                for fld in decl.fields:
                    if fld.implied_group:
                        settings_implied_groups[fld.implied_group] = fld.name

    # 1. Groups & Group IMPLIES Group hierarchy
    for full_xml_id, grp in registry.groups.items():
        if "." not in full_xml_id:
            continue
        grp_node_id = f"group:{full_xml_id}"
        # Section 925: determine if this group is a technical feature flag
        is_technical = (
            full_xml_id in settings_implied_groups
            and grp.category_id in ("base.module_category_hidden", None)
        )
        G.add_node(
            grp_node_id,
            node_type="Group",
            xml_id=full_xml_id,
            name=grp.name,
            category_id=grp.category_id,
            group_type="technical" if is_technical else "role",
            setting_field=settings_implied_groups.get(full_xml_id),
        )

        mod_prefix = full_xml_id.split(".")[0]
        for parent_grp in grp.implied_ids:
            full_parent_grp = parent_grp if "." in parent_grp else f"{mod_prefix}.{parent_grp}"
            parent_node_id = f"group:{full_parent_grp}"
            G.add_edge(grp_node_id, parent_node_id, edge_type="IMPLIES")

    # 1b. Section 925: Add IMPLIES_CONFIGURABLE edges for settings-activated groups
    for group_xml_id, field_name in settings_implied_groups.items():
        target_node = f"group:{group_xml_id}"
        source_node = "group:base.group_user"
        if G.has_node(target_node):
            G.add_edge(
                source_node, target_node,
                edge_type="IMPLIES_CONFIGURABLE",
                setting_field=field_name,
                conditional=True,
            )

    # 2. Rules & Model RESTRICTED_BY Rule -> Rule APPLIES_TO_GROUP Group
    for full_xml_id, rule in registry.rules.items():
        if "." not in full_xml_id:
            continue
        if not getattr(rule, "active", True):
            continue
        rule_node_id = f"rule:{full_xml_id}"
        rule_behavioral_tags = [BehavioralTag.VISIBILITY_RULE.value]
        if domain_force_references_state_fn(rule.domain_force):
            rule_behavioral_tags.append(BehavioralTag.WORKFLOW_RULE.value)
        G.add_node(
            rule_node_id,
            node_type="Rule",
            xml_id=full_xml_id,
            name=rule.name,
            domain_force=rule.domain_force,
            filepath=rule.filepath,
            lineno=rule.lineno,
            perm_read=rule.perm_read,
            perm_write=rule.perm_write,
            perm_create=rule.perm_create,
            perm_unlink=rule.perm_unlink,
            behavioral_tags=rule_behavioral_tags,
            technical_tags=[TechnicalTag.RECORD_RULE.value],
        )

        if rule.model_id:
            raw_m = resolve_model_xmlref(rule.model_id)
            model_node_id = f"model:{raw_m}"
            G.add_edge(model_node_id, rule_node_id, edge_type="RESTRICTED_BY")

        for grp_ref in rule.groups_id:
            mod_prefix = full_xml_id.split(".")[0] if "." in full_xml_id else "base"
            full_grp = grp_ref if "." in grp_ref else f"{mod_prefix}.{grp_ref}"
            grp_node_id = f"group:{full_grp}"
            G.add_edge(rule_node_id, grp_node_id, edge_type="APPLIES_TO_GROUP")

    # 3. CSV Access Control Entries (Model GRANTED_BY AccessEntry)
    for mod_name, mod in modules_dict.items():
        for acl in mod.acl_entries:
            acl_node_id = f"acl:{mod_name}.{acl.xml_id}"
            G.add_node(
                acl_node_id,
                node_type="AccessEntry",
                name=acl.name,
                perm_read=acl.perm_read,
                perm_write=acl.perm_write,
                perm_create=acl.perm_create,
                perm_unlink=acl.perm_unlink,
                all_authenticated=acl.all_authenticated,
                behavioral_tags=[BehavioralTag.VISIBILITY_RULE.value],
                technical_tags=[TechnicalTag.ACL.value],
            )

            raw_m = resolve_model_xmlref(acl.model_id)
            model_node_id = f"model:{raw_m}"
            G.add_edge(model_node_id, acl_node_id, edge_type="GRANTED_BY")

            if acl.group_id:
                grp_node_id = f"group:{acl.group_id}"
                G.add_edge(acl_node_id, grp_node_id, edge_type="APPLIES_TO_GROUP")

    # 4. Server Actions (ir.actions.server) & Automations (base.automation)
    for full_xml_id, sa in registry.server_actions.items():
        if "." not in full_xml_id:
            continue
        sa_node_id = f"server_action:{full_xml_id}"
        G.add_node(
            sa_node_id,
            node_type="ServerAction",
            xml_id=full_xml_id,
            name=sa.name,
            model_id=sa.model_id,
            state=sa.state,
            code=sa.code,
            action_type=getattr(sa, "action_type", "server_action"),
            user_id=getattr(sa, "user_id", ""),
            interval_number=getattr(sa, "interval_number", 1),
            interval_type=getattr(sa, "interval_type", ""),
            behavioral_tags=[],
            technical_tags=[TechnicalTag.SERVER_ACTION.value],
        )

        if sa.model_id:
            raw_m = resolve_model_xmlref(sa.model_id)
            model_node_id = f"model:{raw_m}"
            G.add_edge(sa_node_id, model_node_id, edge_type="TARGETS_MODEL")

    for full_xml_id, ba in registry.base_automations.items():
        if "." not in full_xml_id:
            continue
        ba_node_id = f"automation:{full_xml_id}"
        G.add_node(
            ba_node_id,
            node_type="AutomationRule",
            xml_id=full_xml_id,
            name=ba.name,
            model_id=ba.model_id,
            trigger=ba.trigger,
            behavioral_tags=[],
            technical_tags=[TechnicalTag.CRON.value],
        )

        if ba.model_id:
            raw_m = resolve_model_xmlref(ba.model_id)
            model_node_id = f"model:{raw_m}"
            G.add_edge(ba_node_id, model_node_id, edge_type="TRIGGERED_BY")

        for sa_ref in ba.action_server_ids:
            mod_prefix = full_xml_id.split(".")[0] if "." in full_xml_id else "base"
            full_sa = sa_ref if "." in sa_ref else f"{mod_prefix}.{sa_ref}"
            sa_node_id = f"server_action:{full_sa}"
            G.add_edge(ba_node_id, sa_node_id, edge_type="EXECUTES_ACTION")


__all__ = ["add_security_group_nodes"]

# ── UI Nodes ──────────────────────────────────────────────────────────────

"""
code_intelligence/graph/ui_nodes.py

Sub-graph node and edge builders for menus, workflows, and form buttons.
"""

from typing import Dict
import networkx as nx

from code_intelligence.rules.ontology import BehavioralTag
from code_intelligence.utils import resolve_model_xmlref


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
                module=mod_name,
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
