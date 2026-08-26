"""
code_intelligence/graph_builder.py

NetworkX Knowledge Graph Builder for Odoo Code Intelligence.
Builds the security and architecture knowledge graph connecting models, fields,
methods, groups, record rules, menus, and workflow states.
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
from code_intelligence.semantic_tags import BehavioralTag, TechnicalTag

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
        # Bloc P2 Jour 2-3 (todo/plan.md, todo/contexte.txt section 170):
        # per-build cache of file contents, keyed by filepath, so tagging a
        # model's several methods (all sharing the same source file) never
        # re-reads the same file from disk more than once per build_graph()
        # call. Cleared implicitly every time a new OdooGraphBuilder is
        # constructed -- never stale across separate builds.
        self._source_cache: Dict[str, str] = {}

    def _read_source_cached(self, filepath: str) -> str:
        """Read filepath's full text, cached per build. Returns "" (never
        raises) when the file can't be read -- same conservative discipline
        as every other file-read site in this project: a missing/unreadable
        file degrades a heuristic to "no signal found", never crashes graph
        construction over an annotation that is explicitly best-effort."""
        if filepath not in self._source_cache:
            try:
                self._source_cache[filepath] = Path(filepath).read_text(encoding="utf-8")
            except OSError:
                self._source_cache[filepath] = ""
        return self._source_cache[filepath]

    def _method_has_group_and_raise(
        self, filepath: str, lineno: int, end_lineno: Optional[int]
    ) -> bool:
        """
        Bloc P2 Jour 2-3: textual heuristic for BLOCKING_RULE (todo/plan.md
        line 162's own example: "une methode avec has_group()+raise ->
        tag blocking_rule"). Deliberately a plain substring check on the
        method's own source slice, not a full control-flow analysis --
        same confidence tier as method_override_resolver.py's
        detect_unguarded_super (textual/AST-shape heuristic, not a proof).
        This is a coarser signal than that: it only asks "does this method
        gate something on group membership AND raise an error somewhere",
        without verifying the raise is actually reachable from the
        has_group() check (could be a false positive if the two are
        structurally unrelated within the same method body) or that a
        raise elsewhere is the only guard (could be a false negative if
        the block uses a different mechanism, e.g. returning early without
        an error). Adequate for Jour 2-3's stated purpose -- a coarse
        semantic tag for retrieval/measurement, not a security verdict on
        its own; `analyser_verrous_securite`/semgrep_locks_analyzer.py
        remains the authoritative, condition-level extractor for actual
        security-lock answers.
        """
        if end_lineno is None:
            return False
        source = self._read_source_cached(filepath)
        if not source:
            return False
        lines = source.splitlines()
        if lineno < 1 or end_lineno > len(lines):
            return False
        snippet = "\n".join(lines[lineno - 1:end_lineno])
        return "has_group(" in snippet and "raise " in snippet

    @staticmethod
    def _domain_force_references_state(domain_force: Optional[str]) -> bool:
        """Bloc P2 Jour 2-3: textual check for whether a domain_force
        string references the 'state' field (e.g. `("state", "=", "draft")`)
        -- used to add WORKFLOW_RULE alongside the always-present
        VISIBILITY_RULE tag on a Rule node. Plain substring check on the
        quoted field name, matching how domain_force is stored (raw Python
        literal source text, not a parsed AST) -- same tier of heuristic
        as `_method_has_group_and_raise` above."""
        if not domain_force:
            return False
        return "'state'" in domain_force or '"state"' in domain_force

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
            if mod and mod.manifest:
                depends = mod.manifest.depends
                filepath = mod.manifest.filepath
            else:
                # 2026-08-06 fix: same silent-swallow shape as the
                # topological_sort_modules bug this mirrors (see
                # cross_file_resolver.py / manifest_parser.py::
                # MissingManifestError) -- `depends`/`filepath` used to
                # fall back to [] / "" with zero signal whenever a module
                # had no manifest. rag/graph.py::_load_module() no longer
                # produces manifest=None for real corpus modules (it
                # synthesizes a real fallback or raises), so this branch
                # should be unreachable in production; it's kept only for
                # callers/tests that intentionally build
                # ParsedModule(manifest=None, ...), now with a warning
                # instead of silence so a real regression here is visible.
                depends = []
                filepath = ""
                if mod is not None:
                    _logger.warning(
                        "Module '%s' has no manifest -- Module node's "
                        "'depends'/'filepath' attributes will be empty. If "
                        "'%s' is a real corpus module this indicates a "
                        "missing __manifest__.py that should have raised "
                        "earlier in rag/graph.py::_load_module().",
                        mod_name, mod_name,
                    )
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

            # Bloc P2 Jour 2-3: WORKFLOW_RULE when the model declares a
            # 'state' field -- same detection idiom already used by
            # _add_workflow_nodes_and_edges below (kept independent rather
            # than sharing a helper across the two passes since this one
            # only needs a boolean, not the field object itself).
            model_behavioral_tags: List[str] = []
            if any(f.name == "state" for d in decls for f in d.fields):
                model_behavioral_tags.append(BehavioralTag.WORKFLOW_RULE.value)

            self.G.add_node(
                model_node_id,
                node_type="Model",
                name=model_name,
                inherits_list=all_inherits,
                delegations_dict=all_delegations,
                filepaths=all_filepaths,
                description=model_description,
                description_source=description_source,
                behavioral_tags=model_behavioral_tags,
                technical_tags=[],
            )

            # Model -> Module DEFINED_IN edges: one edge per declaration/extension site
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
            for decl_idx, d in enumerate(decls):
                mod_name_for_d = decl_modules[decl_idx] if decl_idx < len(decl_modules) else "unknown"
                # 1. Fields
                for f in d.fields:
                    field_node_id = f"field:{model_name}.{f.name}"
                    # Bloc P2 Jour 2-3: a compute= field is both a
                    # CALCULATION_RULE (behavioral -- it derives a value)
                    # and a COMPUTED_FIELD (technical -- the concrete Odoo
                    # mechanism). `store` is deliberately not consulted --
                    # whether the computed value is persisted doesn't change
                    # whether it IS a calculation.
                    field_behavioral_tags: List[str] = []
                    field_technical_tags: List[str] = []
                    if f.compute:
                        field_behavioral_tags.append(BehavioralTag.CALCULATION_RULE.value)
                        field_technical_tags.append(TechnicalTag.COMPUTED_FIELD.value)
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
                        behavioral_tags=field_behavioral_tags,
                        technical_tags=field_technical_tags,
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
                    # Accumulate every override site across module inheritance cascade
                    existing_sites = list(self.G.nodes[method_node_id].get("override_sites", [])) \
                        if method_node_id in self.G else []
                    existing_sites.append({
                        "module": mod_name_for_d,
                        "filepath": d.filepath,
                        "lineno": m.lineno,
                        "end_lineno": getattr(m, "end_lineno", None),
                    })
                    # Bloc P2 Jour 2-3: BLOCKING_RULE (behavioral) when this
                    # site's own source contains both has_group() and a
                    # raise (todo/plan.md line 162's own example). CONSTRAINT
                    # (technical) when decorated with @api.constrains.
                    # Checked per-site (not just once for the whole method),
                    # same reasoning as override_sites itself accumulating
                    # per declaration -- a method can be blocking in one
                    # module's override and not in another's.
                    method_behavioral_tags: List[str] = list(
                        self.G.nodes[method_node_id].get("behavioral_tags", [])
                    ) if method_node_id in self.G else []
                    if self._method_has_group_and_raise(
                        d.filepath, m.lineno, getattr(m, "end_lineno", None)
                    ) and BehavioralTag.BLOCKING_RULE.value not in method_behavioral_tags:
                        method_behavioral_tags.append(BehavioralTag.BLOCKING_RULE.value)

                    method_technical_tags: List[str] = list(
                        self.G.nodes[method_node_id].get("technical_tags", [])
                    ) if method_node_id in self.G else []
                    if any(dec.decorator_type == "constrains" for dec in m.decorators) \
                            and TechnicalTag.CONSTRAINT.value not in method_technical_tags:
                        method_technical_tags.append(TechnicalTag.CONSTRAINT.value)

                    self.G.add_node(
                        method_node_id,
                        node_type="Method",
                        name=m.name,
                        model=model_name,
                        api_model=m.api_model,
                        is_instance_method=m.is_instance_method,
                        filepath=d.filepath,
                        lineno=m.lineno,
                        override_sites=existing_sites,
                        behavioral_tags=method_behavioral_tags,
                        technical_tags=method_technical_tags,
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
            if "." not in full_xml_id:
                continue
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
        for full_xml_id, rule in self.registry.rules.items():
            if "." not in full_xml_id:
                continue
            # A rule with active=False is disabled and does not restrict access
            if not getattr(rule, "active", True):
                continue
            rule_node_id = f"rule:{full_xml_id}"
            # Bloc P2 Jour 2-3: every ir.rule is a RECORD_RULE (technical --
            # it IS the concrete artefact) and always at least a
            # VISIBILITY_RULE (behavioral -- ir.rule's core mechanism is a
            # domain-based access restriction, matching architecture.md's
            # "Accès" reasoning block: ACL + Record Rules + Groupes -> Peut
            # voir/Ne peut pas voir). Additionally WORKFLOW_RULE when the
            # domain_force gates on the 'state' field.
            rule_behavioral_tags = [BehavioralTag.VISIBILITY_RULE.value]
            if self._domain_force_references_state(rule.domain_force):
                rule_behavioral_tags.append(BehavioralTag.WORKFLOW_RULE.value)
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
                behavioral_tags=rule_behavioral_tags,
                technical_tags=[TechnicalTag.RECORD_RULE.value],
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
                    # Bloc P2 Jour 2-3: an ir.model.access.csv row is always
                    # an ACL (technical -- it IS the artefact) and always a
                    # VISIBILITY_RULE (behavioral -- same "Accès" reasoning
                    # as Rule above, ACL is the other half of that pair).
                    behavioral_tags=[BehavioralTag.VISIBILITY_RULE.value],
                    technical_tags=[TechnicalTag.ACL.value],
                )

                raw_m = resolve_model_xmlref(acl.model_id)
                model_node_id = f"model:{raw_m}"
                self.G.add_edge(model_node_id, acl_node_id, edge_type="GRANTED_BY")

                if acl.group_id:
                    grp_node_id = f"group:{acl.group_id}"
                    self.G.add_edge(acl_node_id, grp_node_id, edge_type="APPLIES_TO_GROUP")

        # 4. Server Actions (ir.actions.server) & Automations (base.automation)
        # F-08 fix (2026-08-07): same double-indexing defect as the rules
        # loop above (J7), confirmed actively manifesting on 2026-08-06
        # (Q5.1 benchmark: the same sudo() server action analysed and
        # reported twice -- see todo/revue_code_20260806_override_chain.md,
        # finding F5). registry.server_actions indexes each action under
        # both its full and short xml_id; skip the unqualified duplicate.
        for full_xml_id, sa in self.registry.server_actions.items():
            if "." not in full_xml_id:
                continue
            sa_node_id = f"server_action:{full_xml_id}"
            self.G.add_node(
                sa_node_id,
                node_type="ServerAction",
                xml_id=full_xml_id,
                name=sa.name,
                model_id=sa.model_id,
                state=sa.state,
                code=sa.code,
                # Bloc P2 Jour 2-3: SERVER_ACTION (technical -- it IS the
                # artefact). No behavioral tag assigned: an ir.actions.server's
                # `code` field can contain arbitrary Python (blocking,
                # notification, workflow transition, or none of these) --
                # nothing already extracted lets this be determined without
                # guessing, so behavioral_tags stays empty per rules.md
                # Regle 5 ("absence d'information -> non resolu, jamais
                # devine") rather than defaulting to a plausible-sounding tag.
                behavioral_tags=[],
                technical_tags=[TechnicalTag.SERVER_ACTION.value],
            )

            if sa.model_id:
                raw_m = resolve_model_xmlref(sa.model_id)
                model_node_id = f"model:{raw_m}"
                self.G.add_edge(sa_node_id, model_node_id, edge_type="TARGETS_MODEL")

        # F-08 fix (2026-08-07): same double-indexing defect, not yet
        # observed in a benchmark for base_automations specifically but
        # structurally identical to the confirmed server_actions/groups
        # cases above -- fixed proactively rather than waiting for a
        # concrete failure to surface it.
        for full_xml_id, ba in self.registry.base_automations.items():
            if "." not in full_xml_id:
                continue
            ba_node_id = f"automation:{full_xml_id}"
            self.G.add_node(
                ba_node_id,
                node_type="AutomationRule",
                xml_id=full_xml_id,
                name=ba.name,
                model_id=ba.model_id,
                trigger=ba.trigger,
                # Bloc P2 Jour 2-3: tagged CRON (technical) per explicit user
                # instruction for this Jour 2-3 pass -- disclosed imprecision:
                # base.automation is NOT literally ir.cron (it can be trigger-
                # based -- on_create/on_write/etc. -- not just time-based), but
                # architecture.md's Couche 3 closed technical-tag vocabulary
                # (record_rule, acl, constraint, computed_field, server_action,
                # cron) has no dedicated slot for base.automation; CRON is the
                # closest existing bucket rather than inventing a 7th tag
                # outside the closed enumeration Jour 1 deliberately fixed.
                # No behavioral tag: same "don't guess" reasoning as
                # ServerAction above -- an automation's actual business intent
                # (notification, workflow, blocking) lives in the ServerAction
                # it triggers (EXECUTES_ACTION edge), not in this node itself.
                behavioral_tags=[],
                technical_tags=[TechnicalTag.CRON.value],
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
                    # Bloc P2 Jour 5 (todo/plan.md, todo/contexte.txt section
                    # 179): default empty -- populated below once/if the
                    # target model is resolved (a Menu inherits the tags of
                    # the Model it opens; a Menu with no resolvable action
                    # stays untagged, same "no information -> empty, never
                    # guessed" discipline as everywhere else).
                    behavioral_tags=[],
                    technical_tags=[],
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
                    # Bloc P2 Jour 5 (todo/plan.md, todo/contexte.txt section
                    # 179): a Menu inherits the behavioral/technical tags of
                    # the Model it opens -- not a new observation, a pure
                    # propagation of a fact already computed when that
                    # Model node was built (_add_model_field_method_nodes
                    # runs before _add_menu_nodes in build_graph()). Copied
                    # (not referenced) so later mutation of one list can
                    # never alias the other.
                    if model_node_id in self.G:
                        self.G.nodes[menu_node_id]["behavioral_tags"] = list(
                            self.G.nodes[model_node_id].get("behavioral_tags", [])
                        )
                        self.G.nodes[menu_node_id]["technical_tags"] = list(
                            self.G.nodes[model_node_id].get("technical_tags", [])
                        )

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
                    # Bloc P2 Jour 5 (todo/plan.md, todo/contexte.txt section
                    # 179): a WorkflowState node only exists because this
                    # model has a 'state' field -- the same precondition
                    # that already gives the Model node WORKFLOW_RULE
                    # (Jour 2-3). Tautological, not a guess: the node's own
                    # existence proves the tag. No technical tag applies to
                    # a state value itself.
                    behavioral_tags=[BehavioralTag.WORKFLOW_RULE.value],
                    technical_tags=[],
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
