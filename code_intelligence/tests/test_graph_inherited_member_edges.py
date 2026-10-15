"""Computed and dependency edges must point at the declaring model, never at an empty node."""

import ast

from code_intelligence.extractor.manifest import OdooManifest
from code_intelligence.extractor.python import OdooClassVisitor, OdooFieldDeclaration, OdooMethodDeclaration, OdooMethodDecoration, OdooModelDeclaration
from code_intelligence.graph.builder import OdooGraphBuilder
from code_intelligence.graph.integrity_report import build_graph_integrity_report
from code_intelligence.graph.nodes import ParsedModule
from code_intelligence.graph.symbols import build_module_symbol_registry


def _build_graph(declarations):
    modulesDict = {"mod": ParsedModule(manifest=OdooManifest(module_name="mod", filepath="", depends=[]), models=declarations)}
    return OdooGraphBuilder(build_module_symbol_registry(modulesDict), modulesDict).build_graph()


def _graph_with_inherited_members():
    mixin = OdooModelDeclaration(
        class_name="Mixin", filepath="mod/mixin.py", lineno=1, name="mixin.base",
        fields=[OdooFieldDeclaration(name="image", field_type="Binary")],
        methods=[OdooMethodDeclaration(name="_compute_flag", lineno=5)],
    )
    parent = OdooModelDeclaration(
        class_name="Parent", filepath="mod/parent.py", lineno=1, name="parent.model",
        fields=[OdooFieldDeclaration(name="tz", field_type="Char")],
    )
    child = OdooModelDeclaration(
        class_name="Child", filepath="mod/child.py", lineno=1, name="child.model",
        inherit=["mixin.base"], inherits={"parent.model": "parent_id"},
        fields=[OdooFieldDeclaration(name="flag", field_type="Boolean", compute="_compute_flag")],
        methods=[OdooMethodDeclaration(
            name="_compute_offset", lineno=9,
            decorators=[OdooMethodDecoration(decorator_type="depends", trigger_fields=["tz", "image", "write_date"])],
        )],
    )
    return _build_graph([mixin, parent, child])


def test_dependencies_attach_to_the_declaring_model():
    graph = _graph_with_inherited_members()
    assert graph.has_edge("method:child.model._compute_offset", "field:parent.model.tz")
    assert graph.has_edge("method:child.model._compute_offset", "field:mixin.base.image")
    assert graph.has_edge("field:child.model.flag", "method:mixin.base._compute_flag")


def test_no_empty_node_is_created_for_inherited_or_magic_members():
    graph = _graph_with_inherited_members()
    assert not graph.has_node("field:child.model.tz")
    assert not graph.has_node("field:child.model.write_date")
    assert not {"untyped_node", "unresolved_endpoint"} & set(build_graph_integrity_report(graph)["counts"])


def test_extractor_keeps_reference_json_and_properties_fields():
    source = (
        "from odoo import models, fields\n"
        "class Record(models.Model):\n"
        "    _name = 'record.model'\n"
        "    res_id = fields.Many2oneReference(model_field='model')\n"
        "    ref = fields.Reference(selection=[])\n"
        "    distribution = fields.Json()\n"
        "    props = fields.Properties(definition='x')\n"
    )
    visitor = OdooClassVisitor()
    visitor.visit(ast.parse(source))
    names = {field.name for declaration in visitor.declarations for field in declaration.fields}
    assert names == {"res_id", "ref", "distribution", "props"}
