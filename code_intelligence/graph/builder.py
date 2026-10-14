"""Knowledge graph construction from parsed Odoo modules."""

import logging
from pathlib import Path
from typing import Dict, List, Optional
import networkx as nx

from code_intelligence.rules.ontology import BehavioralTag, TechnicalTag
from .nodes import (
    add_security_group_nodes, add_menu_nodes, add_window_action_refs,
    add_view_button_nodes_and_edges, add_workflow_nodes_and_edges,
    ParsedModule, ResolvedSymbolRegistry,
)
from .translations import attach_translations, translation_fingerprint
from .integrity_report import build_graph_integrity_report

_logger = logging.getLogger(__name__)


def _humanize_technical_name(name: str) -> str:
    return name.replace("_", " ").replace(".", " ").strip().title()


def _declares_model(decl, model_name: str) -> bool:
    return bool(decl.name) and model_name not in (decl.inherit or [])


class OdooGraphBuilder:
    def __init__(self, registry: ResolvedSymbolRegistry, modules_dict: Dict[str, ParsedModule]):
        self.registry = registry
        self.modules_dict = modules_dict
        self.G = nx.DiGraph()
        self._source_cache: Dict[str, str] = {}

    def _read_source_cached(self, filepath: str) -> str:
        if filepath not in self._source_cache:
            try:
                self._source_cache[filepath] = Path(filepath).read_text(encoding="utf-8")
            except OSError:
                self._source_cache[filepath] = ""
        return self._source_cache[filepath]

    def _method_has_group_and_raise(self, filepath: str, lineno: int, end_lineno: Optional[int]) -> bool:
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
        if not domain_force:
            return False
        return "'state'" in domain_force or '"state"' in domain_force

    def _add_model_reference_edge(self, sourceNode, modelRef, edgeType, sourceModule, sourceFile, **attributes):
        targetModel = self.registry.resolve_model_ref_or_record(modelRef, sourceModule, sourceFile)
        if targetModel is not None:
            self.G.add_edge(sourceNode, f"model:{targetModel}", edge_type=edgeType, **attributes)

    def build_graph(self) -> nx.DiGraph:
        self._add_module_nodes()
        self._add_model_field_method_nodes()
        self._add_security_group_nodes()
        self._add_workflow_nodes_and_edges()
        self._add_view_button_nodes_and_edges()
        self._add_menu_nodes()
        self._add_window_action_refs()
        entries = [entry for module in self.modules_dict.values() for entry in module.translations]
        self.G.graph["translation_summary"] = attach_translations(self.G, entries)
        self.G.graph["translation_fingerprint"] = translation_fingerprint(entries)
        self.G.graph["unresolved_references"] = [
            {"source_module": reference.source_module, "source_file": reference.source_file,
             "symbol_ref": reference.symbol_ref, "ref_type": reference.ref_type,
             "category": reference.category.value, "detail": reference.detail}
            for reference in self.registry.unresolved_references
        ]
        self.G.graph["integrity_report"] = build_graph_integrity_report(self.G)
        return self.G

    def _add_module_nodes(self):
        for mod_name, mod in self.modules_dict.items():
            node_id = f"module:{mod_name}"
            if mod and mod.manifest:
                depends = mod.manifest.depends
                filepath = mod.manifest.filepath
            else:
                depends = []
                filepath = ""
                if mod is not None:
                    _logger.warning("Module '%s' has no manifest; dependency and source metadata are unavailable.", mod_name)
            self.G.add_node(node_id, node_type="Module", name=mod_name, depends=depends, filepath=filepath)

    def _add_model_field_method_nodes(self):
        for model_name, decls in self.registry.models.items():
            model_node_id = f"model:{model_name}"
            all_inherits = []
            all_delegations = {}
            for d in decls:
                all_inherits.extend(d.inherit)
                all_delegations.update(d.inherits)
            all_filepaths = list(dict.fromkeys(d.filepath for d in decls if d.filepath))
            explicit_description = next((d.description for d in decls if d.description), None)
            model_description = explicit_description or _humanize_technical_name(model_name)
            description_source = "explicit" if explicit_description else "generated"
            model_behavioral_tags: List[str] = []
            if any(f.name == "state" for d in decls for f in d.fields):
                model_behavioral_tags.append(BehavioralTag.WORKFLOW_RULE.value)
            self.G.add_node(
                model_node_id, node_type="Model", name=model_name, inherits_list=all_inherits,
                delegations_dict=all_delegations, filepaths=all_filepaths,
                description=model_description, description_source=description_source,
                behavioral_tags=model_behavioral_tags, technical_tags=[],
            )
            decl_modules = self.registry.model_modules.get(model_name, [])
            module_roles: Dict[str, str] = {}
            filepath_roles: Dict[str, str] = {}
            for d, mod_name in zip(decls, decl_modules):
                decl_role = "declares" if _declares_model(d, model_name) else "extends"
                if module_roles.get(mod_name) != "declares":
                    module_roles[mod_name] = decl_role
                if d.filepath and filepath_roles.get(d.filepath) != "declares":
                    filepath_roles[d.filepath] = decl_role
            for mod_name, role in module_roles.items():
                self.G.add_edge(model_node_id, f"module:{mod_name}", edge_type="DEFINED_IN", role=role)
            self.G.nodes[model_node_id]["filepath_roles"] = filepath_roles

            for decl_idx, d in enumerate(decls):
                mod_name_for_d = decl_modules[decl_idx] if decl_idx < len(decl_modules) else "unknown"
                for parentModel in d.inherit:
                    if parentModel != model_name:
                        self._add_model_reference_edge(model_node_id, parentModel, "EXTENDS", mod_name_for_d, d.filepath)
                for parentModel, foreignKey in d.inherits.items():
                    self._add_model_reference_edge(model_node_id, parentModel, "DELEGATES_TO", mod_name_for_d, d.filepath, fk_field=foreignKey)

                for f in d.fields:
                    field_node_id = f"field:{model_name}.{f.name}"
                    field_behavioral_tags: List[str] = []
                    field_technical_tags: List[str] = []
                    if f.compute:
                        field_behavioral_tags.append(BehavioralTag.CALCULATION_RULE.value)
                        field_technical_tags.append(TechnicalTag.COMPUTED_FIELD.value)
                    self.G.add_node(
                        field_node_id, node_type="Field", name=f.name, model=model_name,
                        field_type=f.field_type, comodel_name=f.comodel_name, inverse_name=f.inverse_name,
                        compute=f.compute, related=f.related, store=f.store, filepath=d.filepath,
                        label=f.string if f.string else _humanize_technical_name(f.name),
                        label_source="explicit" if f.string else "generated",
                        behavioral_tags=field_behavioral_tags, technical_tags=field_technical_tags,
                    )
                    self.G.add_edge(model_node_id, field_node_id, edge_type="HAS_FIELD")
                    if f.comodel_name:
                        self._add_model_reference_edge(field_node_id, f.comodel_name, "RELATES_TO", mod_name_for_d, d.filepath,
                                                       relation_type=f.field_type.lower(), inverse_name=f.inverse_name)
                    if f.compute:
                        method_node_id = f"method:{model_name}.{f.compute}"
                        self.G.add_edge(field_node_id, method_node_id, edge_type="COMPUTED_BY")

                for m in d.methods:
                    method_node_id = f"method:{model_name}.{m.name}"
                    existing_sites = list(self.G.nodes[method_node_id].get("override_sites", [])) if method_node_id in self.G else []
                    existing_sites.append({"module": mod_name_for_d, "filepath": d.filepath,
                                           "lineno": m.lineno, "end_lineno": getattr(m, "end_lineno", None)})
                    method_behavioral_tags: List[str] = list(self.G.nodes[method_node_id].get("behavioral_tags", [])) if method_node_id in self.G else []
                    if self._method_has_group_and_raise(d.filepath, m.lineno, getattr(m, "end_lineno", None)) and BehavioralTag.BLOCKING_RULE.value not in method_behavioral_tags:
                        method_behavioral_tags.append(BehavioralTag.BLOCKING_RULE.value)
                    method_technical_tags: List[str] = list(self.G.nodes[method_node_id].get("technical_tags", [])) if method_node_id in self.G else []
                    if any(dec.decorator_type == "constrains" for dec in m.decorators) and TechnicalTag.CONSTRAINT.value not in method_technical_tags:
                        method_technical_tags.append(TechnicalTag.CONSTRAINT.value)
                    self.G.add_node(
                        method_node_id, node_type="Method", name=m.name, model=model_name,
                        api_model=m.api_model, is_instance_method=m.is_instance_method,
                        filepath=d.filepath, lineno=m.lineno,
                        end_lineno=getattr(m, "end_lineno", None) or (m.lineno + 30),
                        override_sites=existing_sites, behavioral_tags=method_behavioral_tags, technical_tags=method_technical_tags,
                    )
                    for dec in m.decorators:
                        if dec.decorator_type == "depends":
                            for trigger in dec.trigger_fields:
                                trigger_field_id = f"field:{model_name}.{trigger.split('.')[0]}"
                                self.G.add_edge(method_node_id, trigger_field_id, edge_type="DEPENDS_ON", trigger_path=trigger)

    def _add_security_group_nodes(self):
        add_security_group_nodes(self.G, self.registry, self.modules_dict, self._domain_force_references_state)

    def _add_menu_nodes(self):
        add_menu_nodes(self.G, self.modules_dict)

    def _add_window_action_refs(self):
        add_window_action_refs(self.G, self.modules_dict)

    def _add_workflow_nodes_and_edges(self):
        add_workflow_nodes_and_edges(self.G, self.registry, self.modules_dict)

    def _add_view_button_nodes_and_edges(self):
        add_view_button_nodes_and_edges(self.G, self.modules_dict)


__all__ = ["OdooGraphBuilder", "_humanize_technical_name"]
