"""Symbol registries and graph node builders for parsed Odoo modules."""

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Dict, List, Optional

from code_intelligence.extractor.manifest import OdooManifest
from code_intelligence.extractor.python import OdooModelDeclaration
from code_intelligence.extractor.xml import (
    OdooActionRecord,
    OdooBaseAutomationRecord,
    OdooGroupRecord,
    OdooMailTemplateRecord,
    OdooMenuItemRecord,
    OdooReportRecord,
    OdooRuleRecord,
    OdooServerActionRecord,
    OdooViewRecord,
)
from code_intelligence.extractor.csv import OdooAccessEntry
from code_intelligence.model_references import build_model_xmlref_index, resolve_model_ref


class UnresolvedCategory(Enum):
    ABSENT_FROM_CORPUS = "absent_from_corpus"
    CORE_ODOO_OUT_OF_SCOPE = "core_odoo_out_of_scope"
    PROBABLE_TYPO = "probable_typo"


@dataclass
class UnresolvedReference:
    source_module: str
    source_file: str
    symbol_ref: str
    ref_type: str
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
    reports: List[OdooReportRecord] = field(default_factory=list)
    mail_templates: List[OdooMailTemplateRecord] = field(default_factory=list)
    http_routes: List[object] = field(default_factory=list)
    translations: List[object] = field(default_factory=list)
    client_action_models: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class ResolvedSymbolRegistry:
    models: Dict[str, List[OdooModelDeclaration]] = field(default_factory=dict)
    model_modules: Dict[str, List[str]] = field(default_factory=dict)
    groups: Dict[str, OdooGroupRecord] = field(default_factory=dict)
    rules: Dict[str, OdooRuleRecord] = field(default_factory=dict)
    actions: Dict[str, OdooActionRecord] = field(default_factory=dict)
    server_actions: Dict[str, OdooServerActionRecord] = field(default_factory=dict)
    base_automations: Dict[str, OdooBaseAutomationRecord] = field(default_factory=dict)
    menuitems: Dict[str, OdooMenuItemRecord] = field(default_factory=dict)
    views: Dict[str, OdooViewRecord] = field(default_factory=dict)
    resolved_inheritance: Dict[str, List[str]] = field(default_factory=dict)
    unresolved_references: List[UnresolvedReference] = field(default_factory=list)
    detected_cycles: List[List[str]] = field(default_factory=list)
    _modelRefIndex: Optional[dict[str, tuple[str, ...]]] = field(default=None, init=False, repr=False, compare=False)
    _modelRefNames: frozenset[str] = field(default_factory=frozenset, init=False, repr=False, compare=False)

    def resolve_model_ref(self, rawRef: str) -> Optional[str]:
        if self._modelRefIndex is None or self._modelRefNames != self.models.keys():
            self._modelRefNames = frozenset(self.models)
            self._modelRefIndex = build_model_xmlref_index(self._modelRefNames)
        return resolve_model_ref(rawRef, self._modelRefIndex)

    def resolve_model_ref_or_record(self, rawRef: str, sourceModule: str, sourceFile: str) -> Optional[str]:
        modelName = self.resolve_model_ref(rawRef)
        if modelName is not None:
            return modelName
        reference = rawRef or ""
        if not any(
            item.ref_type == "model" and item.symbol_ref == reference
            and item.source_module == sourceModule and item.source_file == sourceFile
            for item in self.unresolved_references
        ):
            self.unresolved_references.append(UnresolvedReference(
                source_module=sourceModule,
                source_file=sourceFile,
                symbol_ref=reference,
                ref_type="model",
                category=_categorize_unresolved(sourceModule, reference),
                detail=f"Model reference '{reference}' is absent or ambiguous in the parsed corpus.",
            ))
        return None


CORE_BASE_MODULES = {
    "base", "mail", "portal", "utm", "bus", "web", "product", "account", "sale", "stock"
}


def _categorize_unresolved(mod_name: str, symbol_ref: str) -> UnresolvedCategory:
    """Categorize an unresolved symbol reference."""
    if "." in symbol_ref:
        prefix = symbol_ref.split(".")[0]
        if prefix in CORE_BASE_MODULES:
            return UnresolvedCategory.CORE_ODOO_OUT_OF_SCOPE
        elif not re.match(r"^[a-zA-Z0-9_\.]+$", symbol_ref):
            return UnresolvedCategory.PROBABLE_TYPO
    if symbol_ref.startswith("base.") or symbol_ref.startswith("mail."):
        return UnresolvedCategory.CORE_ODOO_OUT_OF_SCOPE
    elif symbol_ref.count(".") > 2 or " " in symbol_ref:
        return UnresolvedCategory.PROBABLE_TYPO
    else:
        return UnresolvedCategory.ABSENT_FROM_CORPUS


from typing import Callable
import networkx as nx

from code_intelligence.rules.ontology import BehavioralTag, TechnicalTag
from code_intelligence.graph.state_field import lifecycle_fields
from code_intelligence.graph.workflow_extraction import (
    origin_states,
    selection_values,
    written_states,
    workflow_transition_records,
)
from code_intelligence.utils import qualify_xml_id


def add_security_group_nodes(
    G: nx.DiGraph,
    registry: ResolvedSymbolRegistry,
    modules_dict: Dict[str, ParsedModule],
    domain_force_references_field_fn: Callable[[Optional[str], str], bool],
):
    """Add Group, Rule, AccessEntry, ServerAction, and AutomationRule nodes + security edges."""
    lifecycle = lifecycle_fields(registry, modules_dict)
    settings_implied_groups: Dict[str, str] = {}
    for model_name, decl_list in registry.models.items():
        if model_name == "res.config.settings" or "res.config.settings" in sum(
            (d.inherit for d in decl_list), []
        ):
            for decl in decl_list:
                for fld in decl.fields:
                    if fld.implied_group:
                        settings_implied_groups[fld.implied_group] = fld.name

    for full_xml_id, grp in registry.groups.items():
        if "." not in full_xml_id:
            continue
        grp_node_id = f"group:{full_xml_id}"
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
            full_parent_grp = qualify_xml_id(parent_grp, mod_prefix)
            parent_node_id = f"group:{full_parent_grp}"
            G.add_edge(grp_node_id, parent_node_id, edge_type="IMPLIES")

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

    for full_xml_id, rule in registry.rules.items():
        if "." not in full_xml_id:
            continue
        rule_node_id = f"rule:{full_xml_id}"
        rule_behavioral_tags = [BehavioralTag.VISIBILITY_RULE.value]
        ruleModelName = (
            registry.resolve_model_ref_or_record(rule.model_id, full_xml_id.split('.', 1)[0], rule.filepath)
            if rule.model_id else None
        )
        ruleStateField = lifecycle.get(ruleModelName)
        if ruleStateField and domain_force_references_field_fn(rule.domain_force, ruleStateField):
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
            active=bool(getattr(rule, "active", True)),
            behavioral_tags=rule_behavioral_tags,
            technical_tags=[TechnicalTag.RECORD_RULE.value],
        )
        if ruleModelName is not None:
            G.add_edge(f"model:{ruleModelName}", rule_node_id, edge_type="RESTRICTED_BY")
        for grp_ref in rule.groups_id:
            full_grp = qualify_xml_id(grp_ref, full_xml_id.split(".", 1)[0])
            G.add_edge(rule_node_id, f"group:{full_grp}", edge_type="APPLIES_TO_GROUP")

    for mod_name, mod in modules_dict.items():
        for acl in mod.acl_entries:
            acl_node_id = f"acl:{qualify_xml_id(acl.xml_id, mod_name)}"
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
            modelName = registry.resolve_model_ref_or_record(acl.model_id, mod_name, acl.filepath)
            if modelName is not None:
                G.add_edge(f"model:{modelName}", acl_node_id, edge_type="GRANTED_BY")
            if acl.group_id:
                G.add_edge(acl_node_id, f"group:{qualify_xml_id(acl.group_id, mod_name)}", edge_type="APPLIES_TO_GROUP")

    for full_xml_id, sa in registry.server_actions.items():
        if "." not in full_xml_id:
            continue
        sa_node_id = f"server_action:{full_xml_id}"
        targetModel = registry.resolve_model_ref_or_record(sa.model_id, full_xml_id.split('.', 1)[0], sa.filepath) if sa.model_id else None
        G.add_node(
            sa_node_id,
            node_type="ServerAction",
            xml_id=full_xml_id,
            name=sa.name,
            model_id=sa.model_id,
            target_model=targetModel or "",
            state=sa.state,
            code=sa.code,
            action_type=getattr(sa, "action_type", "server_action"),
            user_id=getattr(sa, "user_id", ""),
            interval_number=getattr(sa, "interval_number", 1),
            interval_type=getattr(sa, "interval_type", ""),
            behavioral_tags=[],
            technical_tags=[TechnicalTag.SERVER_ACTION.value],
        )
        if targetModel is not None:
            G.add_edge(sa_node_id, f"model:{targetModel}", edge_type="TARGETS_MODEL")

    for full_xml_id, ba in registry.base_automations.items():
        if "." not in full_xml_id:
            continue
        ba_node_id = f"automation:{full_xml_id}"
        targetModel = registry.resolve_model_ref_or_record(ba.model_id, full_xml_id.split('.', 1)[0], ba.filepath) if ba.model_id else None
        G.add_node(
            ba_node_id,
            node_type="AutomationRule",
            xml_id=full_xml_id,
            name=ba.name,
            model_id=ba.model_id,
            target_model=targetModel or "",
            trigger=ba.trigger,
            behavioral_tags=[],
            technical_tags=[TechnicalTag.CRON.value],
        )
        if targetModel is not None:
            G.add_edge(ba_node_id, f"model:{targetModel}", edge_type="TRIGGERED_BY")
        for sa_ref in ba.action_server_ids:
            full_sa = qualify_xml_id(sa_ref, full_xml_id.split(".", 1)[0])
            G.add_edge(ba_node_id, f"server_action:{full_sa}", edge_type="EXECUTES_ACTION")


def add_menu_nodes(
    G: nx.DiGraph,
    registry: ResolvedSymbolRegistry,
    modules_dict: Dict[str, ParsedModule],
):
    """Add Menu nodes as fuzzy-matching targets and link to models via actions."""
    clientActionModels = {tag: models for mod in modules_dict.values() for tag, models in mod.client_action_models.items()}
    for mod_name, mod in modules_dict.items():
        for menu in mod.menuitems:
            full_xml_id = qualify_xml_id(menu.xml_id, mod_name)
            menu_node_id = f"menu:{full_xml_id}"
            action_ref = ""
            action_rec = None
            if menu.action:
                action_ref = qualify_xml_id(menu.action, mod_name)
                action_rec = registry.actions.get(action_ref) or registry.actions.get(menu.action)
            G.add_node(
                menu_node_id,
                node_type="Menu",
                xml_id=full_xml_id,
                module=mod_name,
                name=menu.name or (action_rec.name if action_rec else ""),
                sequence=menu.sequence,
                filepath=menu.filepath,
                action_ref=menu.action or "",
                action_type=action_rec.action_type if action_rec else "",
                action_tag=action_rec.tag if action_rec else "",
                action_domain=action_rec.domain if action_rec else "",
                groups=[qualify_xml_id(g, mod_name) for g in menu.groups],
                behavioral_tags=[],
                technical_tags=[],
            )
            for g in menu.groups:
                G.add_edge(menu_node_id, f"group:{qualify_xml_id(g, mod_name)}", edge_type="APPLIES_TO_GROUP")
            if menu.parent:
                G.add_edge(menu_node_id, f"menu:{qualify_xml_id(menu.parent, mod_name)}", edge_type="CHILD_OF")
            if not menu.action:
                continue
            if action_rec and action_rec.action_type == "client":
                for model in clientActionModels.get(action_rec.tag, ()):
                    if f"model:{model}" in G:
                        G.add_edge(menu_node_id, f"model:{model}", edge_type="OPENS_MODEL", via="client_action_js")
                continue
            target_model = None
            via = None
            if action_rec and action_rec.res_model:
                target_model = registry.resolve_model_ref_or_record(action_rec.res_model, mod_name, menu.filepath)
                via = "act_window"
            if not target_model:
                sa_rec = registry.server_actions.get(action_ref) or registry.server_actions.get(menu.action)
                if sa_rec:
                    G.nodes[menu_node_id]["action_type"] = "server_action"
                if sa_rec and sa_rec.model_id:
                    target_model = registry.resolve_model_ref_or_record(sa_rec.model_id, mod_name, menu.filepath)
                    via = "server_action"
            if target_model:
                model_node_id = f"model:{target_model}"
                G.add_edge(menu_node_id, model_node_id, edge_type="OPENS_MODEL", via=via)
                if model_node_id in G:
                    G.nodes[menu_node_id]["behavioral_tags"] = list(G.nodes[model_node_id].get("behavioral_tags", []))
                    G.nodes[menu_node_id]["technical_tags"] = list(G.nodes[model_node_id].get("technical_tags", []))


def add_window_action_refs(G: nx.DiGraph, modules_dict: Dict[str, ParsedModule]):
    """Record on each model the window actions that target it, whether or not a menu opens them."""
    for mod_name, mod in modules_dict.items():
        for action in mod.actions:
            model_node_id = f"model:{action.res_model}"
            if not action.res_model or model_node_id not in G:
                continue
            refs = G.nodes[model_node_id].setdefault("window_actions", [])
            full_xml_id = qualify_xml_id(action.xml_id, mod_name)
            if all(ref["xml_id"] != full_xml_id for ref in refs):
                refs.append({"xml_id": full_xml_id, "name": action.name, "module": mod_name})


def add_workflow_nodes_and_edges(
    G: nx.DiGraph,
    registry: ResolvedSymbolRegistry,
    modules_dict: Dict[str, ParsedModule],
):
    """Build the workflow sub-graph from the real selection values and the code of each button."""
    lifecycle = lifecycle_fields(registry, modules_dict)
    for model_name, decls in registry.models.items():
        stateField = lifecycle.get(model_name)
        if not stateField:
            continue
        if f"model:{model_name}" in G:
            G.nodes[f"model:{model_name}"]["state_field"] = stateField
        selection = selection_values(decls, stateField)
        form_buttons = []
        for mod in modules_dict.values():
            for view in mod.views:
                if view.model == model_name:
                    form_buttons.extend(view.buttons)
        transitions = []
        for btn in form_buttons:
            if not btn.name:
                continue
            origins = origin_states(btn.states, btn.invisible, selection, stateField)
            targets = [state for state in written_states(decls, btn.name, stateField) if selection is None or state in selection]
            if origins and targets:
                transitions.append((btn, origins, targets))
        states = list(selection) if selection else []
        for _, origins, targets in transitions:
            for state in origins + targets:
                if state not in states:
                    states.append(state)
        for st in states:
            G.add_node(
                f"state:{model_name}.{st}",
                node_type="WorkflowState",
                model=model_name,
                state_value=st,
                state_field=stateField,
                behavioral_tags=[BehavioralTag.WORKFLOW_RULE.value],
                technical_tags=[],
            )
        for btn, origins, targets in transitions:
            for orig in origins:
                for target in targets:
                    orig_node_id = f"state:{model_name}.{orig}"
                    target_node_id = f"state:{model_name}.{target}"
                    if orig == target:
                        continue
                    transition = {
                        "method_name": btn.name,
                        "label_bouton": btn.string,
                        "groupe_requis": list(btn.groups or []),
                        "alternative": len(targets) > 1,
                    }
                    if G.has_edge(orig_node_id, target_node_id):
                        edge_data = G.edges[orig_node_id, target_node_id]
                        if edge_data.get("edge_type") != "TRANSITIONS_VIA":
                            continue
                        records = workflow_transition_records(edge_data)
                        if transition not in records:
                            records.append(transition)
                        edge_data["button_transitions"] = records
                        continue
                    G.add_edge(
                        orig_node_id,
                        target_node_id,
                        edge_type="TRANSITIONS_VIA",
                        method_name=btn.name,
                        label_bouton=btn.string,
                        groupe_requis=list(btn.groups or []),
                        alternative=len(targets) > 1,
                        button_transitions=[transition],
                    )


def add_view_button_nodes_and_edges(G: nx.DiGraph, modules_dict: Dict[str, ParsedModule]):
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
                    G.add_node(button_node_id, node_type="Button", name=btn.name, label=btn.string,
                               groups=btn.groups, invisible=btn.invisible, model=model_name)
                if G.has_node(model_node_id):
                    G.add_edge(model_node_id, button_node_id, edge_type="HAS_BUTTON", method_name=btn.name,
                               label_bouton=btn.string, groupe_requis=btn.groups, invisible=btn.invisible)


__all__ = [
    "UnresolvedCategory", "UnresolvedReference", "ParsedModule", "ResolvedSymbolRegistry", "CORE_BASE_MODULES",
    "add_security_group_nodes", "add_menu_nodes", "add_window_action_refs",
    "add_workflow_nodes_and_edges", "add_view_button_nodes_and_edges",
]
