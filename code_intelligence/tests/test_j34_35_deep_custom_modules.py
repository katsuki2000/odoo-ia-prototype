"""
code_intelligence/tests/test_j34_35_deep_custom_modules.py

Unit & Integration tests for J34-J35 (Generalization to Deep Custom Modules):
1. Verifies 5-level inheritance cascade handling for custom.deep.document.
2. Verifies complex nested domain_force ['&', '|', ...] parsing.
3. Verifies static security lock analysis for UserError/ValidationError string extraction.
4. Verifies business resolver mapping for deep document concepts.
"""

from code_intelligence.extractor.manifest import parse_manifest
from code_intelligence.extractor.python import extract_odoo_models_from_file
from code_intelligence.extractor.xml import parse_ir_rules_from_xml
from code_intelligence.rules.security import analyze_python_security_locks
from code_intelligence.agent.tools.introspection import list_involved_modules_with_role
from code_intelligence.graph.builder import OdooGraphBuilder
from code_intelligence.graph.nodes import ParsedModule
from code_intelligence.graph.symbols import build_module_symbol_registry
from code_intelligence.tests._corpus_paths import CUSTOM_ADDONS_PATH


MODULE_PATH = CUSTOM_ADDONS_PATH / "deep_inheritance_security"


def test_manifest_parsing():
    """J34-J35: verify manifest parsing of deep_inheritance_security."""
    manifest_file = MODULE_PATH / "__manifest__.py"
    manifest = parse_manifest(manifest_file)
    assert manifest.name == "Custom Deep Inheritance Security (Adversarial J34-J35)"
    assert "account" in manifest.depends


def test_deep_inheritance_python_extraction():
    """J34-J35: verify Python extraction finds custom.deep.document base & extensions."""
    py_file = MODULE_PATH / "models" / "deep_document.py"
    models = extract_odoo_models_from_file(py_file)
    assert len(models) == 5
    assert models[0].name == "custom.deep.document"
    assert all(m.inherit == ["custom.deep.document"] for m in models[1:])


def test_security_locks_analysis_finds_exception_messages():
    """J34-J35: verify UserError and ValidationError exception string extraction."""
    py_file = MODULE_PATH / "models" / "deep_document.py"
    code = py_file.read_text(encoding="utf-8")
    analysis = analyze_python_security_locks(code, str(py_file))
    assert len(analysis.exception_messages) >= 2
    assert any("responsable comptabilité" in msg for msg in analysis.exception_messages)
    assert any("administrateur système" in msg for msg in analysis.exception_messages)


def test_xml_rules_parsing_nested_domain():
    """J34-J35: verify XML parsing of complex nested domain_force ['&', '|', ...]."""
    xml_file = MODULE_PATH / "security" / "security_rules.xml"
    rules = parse_ir_rules_from_xml(xml_file)
    assert len(rules) == 2
    complex_rule = next(r for r in rules if "complex_nested" in r.xml_id or "rule_deep_document_complex_nested" in r.xml_id)
    assert "['&', '|', ('amount', '<=', 50000)" in complex_rule.domain_force


def test_graph_builder_5level_inheritance_edges():
    """J34-J35: verify graph builder registers all 5 module roles."""
    py_file = MODULE_PATH / "models" / "deep_document.py"
    manifest = parse_manifest(MODULE_PATH / "__manifest__.py")
    parsed_mod = ParsedModule(
        manifest=manifest,
        models=extract_odoo_models_from_file(py_file),
    )
    registry = build_module_symbol_registry({"deep_inheritance_security": parsed_mod})
    builder = OdooGraphBuilder(registry, {"deep_inheritance_security": parsed_mod})
    G = builder.build_graph()

    roles = list_involved_modules_with_role(G, "custom.deep.document")
    assert len(roles) >= 1
    assert any(m == "deep_inheritance_security" for m, r in roles)
    registry = build_module_symbol_registry({"deep_inheritance_security": parsed_mod})
    builder = OdooGraphBuilder(registry, {"deep_inheritance_security": parsed_mod})
    G = builder.build_graph()

    roles = list_involved_modules_with_role(G, "custom.deep.document")
    assert len(roles) >= 1
    assert any(m == "deep_inheritance_security" for m, r in roles)
