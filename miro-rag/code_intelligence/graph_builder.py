"""
code_intelligence/graph_builder.py

NetworkX Knowledge Graph Builder for Odoo Code Intelligence.
Implements Story A3.1:
  - A3.1.1 & A3.1.2: Node creation (Model, Field, Method, Group, Rule, Module, AccessEntry, WorkflowState).
  - A3.1.3: Typed edge creation (EXTENDS, DELEGATES_TO, HAS_FIELD, RELATES_TO, COMPUTED_BY, DEPENDS_ON, RESTRICTED_BY, APPLIES_TO_GROUP, IMPLIES, GRANTED_BY, DEFINED_IN).
  - A3.1.4: JSON Graph Serialization (node_link_data / node_link_graph per DT-4).
  - A3.1.5: Workflow Sub-Graph (WorkflowState nodes + TRANSITIONS_VIA edges).
  - B0 (bloc 0 du plan d'agent): Menu nodes + business-language labels (string=/_description)
    on Field/Model nodes, required as fuzzy-matching targets for the business-name -> technical-name resolver.
"""

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import logging

import networkx as nx

from code_intelligence.cross_file_resolver import (
    ParsedModule,
    ResolvedSymbolRegistry,
    build_module_symbol_registry,
)
from code_intelligence.utils import resolve_model_xmlref

_logger = logging.getLogger(__name__)


def _humanize_technical_name(name: str) -> str:
    """
    B0 fallback: when a field has no explicit string=, Odoo itself displays
    the technical name humanized this way in the UI (e.g. amount_total ->
    "Amount Total"). We replicate that here so the resolver has something
    to fuzzy-match against even for the ~60% of fields that skip string=.
    """
    return name.replace("_", " ").replace(".", " ").strip().title()


class OdooGraphBuilder:
    """
    Constructs a NetworkX DiGraph from ParsedModules and ResolvedSymbolRegistry.
    """

    def __init__(self, registry: ResolvedSymbolRegistry, modules_dict: Dict[str, ParsedModule]):
        self.registry = registry
        self.modules_dict = modules_dict
        self.G = nx.DiGraph()

    def build_graph(self) -> nx.DiGraph:
        """
        Build full Knowledge Graph with typed nodes and edges.
        """
        self._add_module_nodes()
        self._add_model_field_method_nodes()
        self._add_security_group_nodes()
        self._add_workflow_nodes_and_edges()
        self._add_menu_nodes()

        return self.G

    def _add_module_nodes(self):
        """Add Module nodes and module dependency edges."""
        for mod_name, mod in self.modules_dict.items():
            node_id = f"module:{mod_name}"
            depends = mod.manifest.depends if (mod and mod.manifest) else []
            filepath = mod.manifest.filepath if (mod and mod.manifest) else ""
            self.G.add_node(
                node_id,
                node_type="Module",
                name=mod_name,
                depends=depends,
                filepath=filepath,
            )

    def _add_model_field_method_nodes(self):
        """Add Model, Field, Method, Rule, and AccessEntry nodes + their edges."""
        for model_name, decls in self.registry.models.items():
            model_node_id = f"model:{model_name}"

            # Combine model attributes across extensions
            all_inherits = []
            all_delegations = {}
            for d in decls:
                all_inherits.extend(d.inherit)
                all_delegations.update(d.inherits)

            # Collect source filepaths for this model across declarations
            all_filepaths = list(dict.fromkeys(d.filepath for d in decls if d.filepath))

            # B0: business-language description (_description = "...").
            # Usually only set on the base declaration (the one with _name); extensions
            # rarely redeclare it, so take the first non-empty value found across decls.
            # Same ~50% gap as fields, same fallback: humanize the technical model name
            # (e.g. custom.credit.note.approval.regional -> "Custom Credit Note Approval
            # Regional") rather than leaving the resolver with nothing to match.
            explicit_description = next((d.description for d in decls if d.description), None)
            model_description = explicit_description or _humanize_technical_name(model_name)
            description_source = "explicit" if explicit_description else "generated"

            self.G.add_node(
                model_node_id,
                node_type="Model",
                name=model_name,
                inherits_list=all_inherits,
                delegations_dict=all_delegations,
                filepaths=all_filepaths,
                description=model_description,
                description_source=description_source,
            )

            # Model -> Module DEFINED_IN edges (Bloc 8 / J28-29).
            # One edge per real declaration site, not a single one picked
            # from decls[0] -- a model declared with _name in one module
            # and extended via _inherit in others is a genuinely ambiguous
            # symbol (which module is "the" origin?), and collapsing it to
            # decls[0]'s module arbitrarily (order = topological load order,
            # not authorship) previously hid every other module from
            # lister_modules_impliques. Every candidate module is now kept,
            # tagged with its role, so the agent/user can see and decide
            # instead of the tool silently picking one.
            decl_modules = self.registry.model_modules.get(model_name, [])
            for idx, d in enumerate(decls):
                if idx >= len(decl_modules):
                    continue
                mod_name = decl_modules[idx]
                role = "declares" if d.name else "extends"
                self.G.add_edge(
                    model_node_id, f"module:{mod_name}",
                    edge_type="DEFINED_IN", role=role,
                )

            # Model inheritance edges (EXTENDS and DELEGATES_TO)
            for parent_model in all_inherits:
                parent_node_id = f"model:{parent_model}"
                self.G.add_edge(model_node_id, parent_node_id, edge_type="EXTENDS")

            for parent_model, fk_field in all_delegations.items():
                parent_node_id = f"model:{parent_model}"
                self.G.add_edge(
                    model_node_id,
                    parent_node_id,
                    edge_type="DELEGATES_TO",
                    fk_field=fk_field
                )

            # Process fields & methods for this model
            for d in decls:
                # 1. Fields
                for f in d.fields:
                    field_node_id = f"field:{model_name}.{f.name}"
                    self.G.add_node(
                        field_node_id,
                        node_type="Field",
                        name=f.name,
                        model=model_name,
                        field_type=f.field_type,
                        comodel_name=f.comodel_name,
                        inverse_name=f.inverse_name,
                        compute=f.compute,
                        related=f.related,
                        store=f.store,
                        filepath=d.filepath,
                        # B0: business-language label (string=) as fuzzy-matching target.
                        # ~60% of fields skip string= in practice; Odoo itself falls back
                        # to a humanized technical name in the UI, so we replicate that
                        # fallback here rather than leaving a resolver-side gap.
                        # label_source lets the resolver (and any audit) tell an author's
                        # intentional label apart from a machine-derived one.
                        label=f.string if f.string else _humanize_technical_name(f.name),
                        label_source="explicit" if f.string else "generated",
                    )
                    # Model HAS_FIELD Field
                    self.G.add_edge(model_node_id, field_node_id, edge_type="HAS_FIELD")

                    # Relational field RELATES_TO Model
                    if f.comodel_name:
                        comodel_node_id = f"model:{f.comodel_name}"
                        self.G.add_edge(
                            field_node_id,
                            comodel_node_id,
                            edge_type="RELATES_TO",
                            relation_type=f.field_type.lower(),
                            inverse_name=f.inverse_name
                        )

                    # COMPUTED_BY edge
                    if f.compute:
                        method_node_id = f"method:{model_name}.{f.compute}"
                        self.G.add_edge(field_node_id, method_node_id, edge_type="COMPUTED_BY")

                # 2. Methods
                for m in d.methods:
                    method_node_id = f"method:{model_name}.{m.name}"
                    self.G.add_node(
                        method_node_id,
                        node_type="Method",
                        name=m.name,
                        model=model_name,
                        api_model=m.api_model,
                        is_instance_method=m.is_instance_method,
                        filepath=d.filepath,
                        lineno=m.lineno,
                    )

                    # Method DEPENDS_ON Field (from @api.depends)
                    for dec in m.decorators:
                        if dec.decorator_type == "depends":
                            for trigger in dec.trigger_fields:
                                trigger_field_id = f"field:{model_name}.{trigger.split('.')[0]}"
                                self.G.add_edge(method_node_id, trigger_field_id, edge_type="DEPENDS_ON", trigger_path=trigger)

    def _add_security_group_nodes(self):
        """Add Group, Rule, AccessEntry nodes and security edges."""
        # 1. Groups & Group IMPLIES Group hierarchy
        for full_xml_id, grp in self.registry.groups.items():
            grp_node_id = f"group:{full_xml_id}"
            self.G.add_node(
                grp_node_id,
                node_type="Group",
                xml_id=full_xml_id,
                name=grp.name,
                category_id=grp.category_id,
            )

            for parent_grp in grp.implied_ids:
                parent_node_id = f"group:{parent_grp}"
                self.G.add_edge(grp_node_id, parent_node_id, edge_type="IMPLIES")

        # 2. Rules & Model RESTRICTED_BY Rule -> Rule APPLIES_TO_GROUP Group
        # Bloc 1 J7 finding F-08: registry.rules indexes each rule under BOTH
        # its full xml_id and its short xml_id (both keys pointing to the
        # SAME rule object -- see cross_file_resolver.build_module_symbol_registry).
        # Iterating .items() naively therefore builds TWO graph nodes per rule,
        # and the short-key duplicate has no '.' in it, so mod_prefix below
        # silently fell back to the hardcoded literal "base" instead of the
        # rule's real module -- producing a hallucinated group reference like
        # "group:base.group_avoir_regional" that does not exist. Skipping
        # entries without a '.' is safe: a fully-qualified key is guaranteed
        # to exist for every rule by construction.
        for full_xml_id, rule in self.registry.rules.items():
            if "." not in full_xml_id:
                continue
            # Bloc 1 J7 finding F-06: a rule with active=False in Odoo is
            # disabled and must not restrict access. Without this check it
            # was silently included in the graph and evaluated as active by
            # evaluer_regles_enregistrement, producing a phantom restriction.
            if not getattr(rule, "active", True):
                continue
            rule_node_id = f"rule:{full_xml_id}"
            self.G.add_node(
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
            )

            if rule.model_id:
                raw_m = resolve_model_xmlref(rule.model_id)
                model_node_id = f"model:{raw_m}"
                self.G.add_edge(model_node_id, rule_node_id, edge_type="RESTRICTED_BY")

            for grp_ref in rule.groups_id:
                mod_prefix = full_xml_id.split(".")[0] if "." in full_xml_id else "base"
                full_grp = grp_ref if "." in grp_ref else f"{mod_prefix}.{grp_ref}"
                grp_node_id = f"group:{full_grp}"
                self.G.add_edge(rule_node_id, grp_node_id, edge_type="APPLIES_TO_GROUP")

        # 3. CSV Access Control Entries (Model GRANTED_BY AccessEntry)
        for mod_name, mod in self.modules_dict.items():
            for acl in mod.acl_entries:
                acl_node_id = f"acl:{mod_name}.{acl.xml_id}"
                self.G.add_node(
                    acl_node_id,
                    node_type="AccessEntry",
                    name=acl.name,
                    perm_read=acl.perm_read,
                    perm_write=acl.perm_write,
                    perm_create=acl.perm_create,
                    perm_unlink=acl.perm_unlink,
                    all_authenticated=acl.all_authenticated,
                )

                raw_m = resolve_model_xmlref(acl.model_id)
                model_node_id = f"model:{raw_m}"
                self.G.add_edge(model_node_id, acl_node_id, edge_type="GRANTED_BY")

                if acl.group_id:
                    grp_node_id = f"group:{acl.group_id}"
                    self.G.add_edge(acl_node_id, grp_node_id, edge_type="APPLIES_TO_GROUP")

        # 4. Server Actions (ir.actions.server) & Automations (base.automation)
        for full_xml_id, sa in self.registry.server_actions.items():
            sa_node_id = f"server_action:{full_xml_id}"
            self.G.add_node(
                sa_node_id,
                node_type="ServerAction",
                xml_id=full_xml_id,
                name=sa.name,
                model_id=sa.model_id,
                state=sa.state,
                code=sa.code,
            )

            if sa.model_id:
                raw_m = resolve_model_xmlref(sa.model_id)
                model_node_id = f"model:{raw_m}"
                self.G.add_edge(sa_node_id, model_node_id, edge_type="TARGETS_MODEL")

        for full_xml_id, ba in self.registry.base_automations.items():
            ba_node_id = f"automation:{full_xml_id}"
            self.G.add_node(
                ba_node_id,
                node_type="AutomationRule",
                xml_id=full_xml_id,
                name=ba.name,
                model_id=ba.model_id,
                trigger=ba.trigger,
            )

            if ba.model_id:
                raw_m = resolve_model_xmlref(ba.model_id)
                model_node_id = f"model:{raw_m}"
                self.G.add_edge(ba_node_id, model_node_id, edge_type="TRIGGERED_BY")

            for sa_ref in ba.action_server_ids:
                mod_prefix = full_xml_id.split(".")[0] if "." in full_xml_id else "base"
                full_sa = sa_ref if "." in sa_ref else f"{mod_prefix}.{sa_ref}"
                sa_node_id = f"server_action:{full_sa}"
                self.G.add_edge(ba_node_id, sa_node_id, edge_type="EXECUTES_ACTION")

    def _add_menu_nodes(self):
        """
        B0: Add Menu nodes as fuzzy-matching targets for the business-name -> technical-name
        resolver ("titres de menu" per the plan).

        A menu item (ir.ui.menu) does not reference a model directly -- it points to an
        action (action="..."), and the action (ir.actions.server / act_window, indexed in
        registry.actions as OdooActionRecord) carries res_model. We resolve through that
        chain: Menu -> Action -> Model. If the action can't be resolved (menu is a pure
        folder/separator with no action, or the action lives outside this corpus), the
        Menu node is still created but left without an OPENS_MODEL edge -- better an
        unresolved edge than a guessed one.
        """
        for mod_name, mod in self.modules_dict.items():
            for menu in mod.menuitems:
                full_xml_id = menu.xml_id if "." in menu.xml_id else f"{mod_name}.{menu.xml_id}"
                menu_node_id = f"menu:{full_xml_id}"

                self.G.add_node(
                    menu_node_id,
                    node_type="Menu",
                    xml_id=full_xml_id,
                    name=menu.name,
                    sequence=menu.sequence,
                    filepath=menu.filepath,
                    # Raw action ref as written in the XML (empty string if none).
                    # Kept even when unresolved so a coverage check can tell "folder
                    # menu with no action at all" (expected, no bug) apart from
                    # "has an action reference but it didn't resolve" (real gap).
                    action_ref=menu.action or "",
                )

                # Menu -> parent Menu (tree structure, useful for disambiguation later)
                if menu.parent:
                    parent_full = menu.parent if "." in menu.parent else f"{mod_name}.{menu.parent}"
                    self.G.add_edge(menu_node_id, f"menu:{parent_full}", edge_type="CHILD_OF")

                if not menu.action:
                    continue

                action_ref = menu.action if "." in menu.action else f"{mod_name}.{menu.action}"

                # Try ir.actions.act_window first (the common case).
                action_rec = self.registry.actions.get(action_ref) or self.registry.actions.get(menu.action)
                target_model = action_rec.res_model if (action_rec and action_rec.res_model) else None
                via = "act_window" if target_model else None

                # Fallback: ir.actions.server (e.g. action_new_bank_setting) also
                # carries a model_id and is a legitimate menu target -- not resolving
                # it was a real coverage gap, not a "no action" folder menu.
                if not target_model:
                    sa_rec = self.registry.server_actions.get(action_ref) or self.registry.server_actions.get(menu.action)
                    if sa_rec and sa_rec.model_id:
                        target_model = resolve_model_xmlref(sa_rec.model_id)
                        via = "server_action"

                if target_model:
                    model_node_id = f"model:{target_model}"
                    self.G.add_edge(menu_node_id, model_node_id, edge_type="OPENS_MODEL", via=via)

    def _add_workflow_nodes_and_edges(self):
        """
        Build Workflow Sub-Graph (A3.1.5).
        Creates WorkflowState nodes and TRANSITIONS_VIA edges linked to form view buttons and methods.
        """
        for model_name, decls in self.registry.models.items():
            # Check if model has a 'state' field (Selection field)
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

            # Standard Odoo state transitions for workflow models (e.g. sale.order: draft -> sent -> sale -> cancel)
            # Find view buttons for this model across parsed modules
            form_buttons = []
            for mod in self.modules_dict.values():
                for view in mod.views:
                    if view.model == model_name:
                        form_buttons.extend(view.buttons)

            # Create state nodes for common states if state field exists
            common_states = ["draft", "sent", "sale", "done", "cancel", "confirm", "validate"]
            for st in common_states:
                state_node_id = f"state:{model_name}.{st}"
                self.G.add_node(
                    state_node_id,
                    node_type="WorkflowState",
                    model=model_name,
                    state_value=st,
                )

            # Connect state nodes via button transition edges
            for btn in form_buttons:
                if not btn.states or not btn.name:
                    continue

                origin_states = [s.strip() for s in btn.states.split(",") if s.strip()]
                # Infer target state from method name convention (e.g. action_confirm -> sale/confirm)
                target_st = "sale" if "confirm" in btn.name else ("cancel" if "cancel" in btn.name else "done")

                for orig in origin_states:
                    orig_node_id = f"state:{model_name}.{orig}"
                    target_node_id = f"state:{model_name}.{target_st}"

                    self.G.add_edge(
                        orig_node_id,
                        target_node_id,
                        edge_type="TRANSITIONS_VIA",
                        method_name=btn.name,
                        label_bouton=btn.string,
                        groupe_requis=btn.groups,
                    )


def save_graph_to_json(G: nx.DiGraph, filepath: Path):
    """Serialize NetworkX graph to JSON file using node_link_data per DT-4."""
    data = nx.node_link_data(G)
    filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    _logger.info("Saved Knowledge Graph to %s (%d nodes, %d edges)", filepath, G.number_of_nodes(), G.number_of_edges())


def load_graph_from_json(filepath: Path) -> nx.DiGraph:
    """Deserialize NetworkX graph from JSON file using node_link_graph per DT-4."""
    content = filepath.read_text(encoding="utf-8")
    data = json.loads(content)
    G = nx.node_link_graph(data)
    return G


def benchmark_graph_traversal(G: nx.DiGraph, start_node: str, max_hops: int = 5) -> Tuple[float, List[str]]:
    """
    Benchmark 5-hop path traversal performance (A3.1.6).
    Returns (elapsed_ms, sample_path).
    """
    t0 = time.perf_counter()

    # Perform BFS / shortest path traversal up to max_hops
    visited_nodes = []
    if start_node in G:
        paths = nx.single_source_shortest_path(G, start_node, cutoff=max_hops)
        for target, path in paths.items():
            if len(path) == max_hops + 1:
                visited_nodes = path
                break

    t1 = time.perf_counter()
    elapsed_ms = (t1 - t0) * 1000.0
    return elapsed_ms, visited_nodes
