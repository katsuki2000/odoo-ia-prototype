"""Section 1416: inactive rules kept but not enforced, ACL ids qualified once, ACLs declared in XML extracted."""
import networkx as nx

from code_intelligence.extractor.csv import OdooAccessEntry
from code_intelligence.extractor.xml import parse_access_entries_from_xml, parse_ir_rules_from_xml
from code_intelligence.graph.nodes import ParsedModule, add_security_group_nodes
from code_intelligence.graph.symbols import build_module_symbol_registry
from code_intelligence.rules.access_evaluator import _eval_single_permission
from code_intelligence.rules.record_rules import evaluate_record_rules

SECURITY_XML = """<?xml version="1.0"?>
<odoo>
  <record id="access_wizard" model="ir.model.access">
    <field name="name">wizard access</field>
    <field name="model_id" ref="model_demo_wizard"/>
    <field name="group_id" ref="base.group_user"/>
    <field name="perm_read">1</field>
    <field name="perm_write">1</field>
  </record>
  <record id="rule_active" model="ir.rule">
    <field name="name">active rule</field>
    <field name="model_id" ref="model_demo_wizard"/>
    <field name="domain_force">[('a', '=', 1)]</field>
  </record>
  <record id="rule_inactive" model="ir.rule">
    <field name="name">inactive rule</field>
    <field name="model_id" ref="model_demo_wizard"/>
    <field name="active">0</field>
    <field name="domain_force">[('b', '=', 2)]</field>
  </record>
</odoo>
"""


class _Manifest:
    depends = []
    filepath = "demo/__manifest__.py"


def _graph_with_rules():
    G = nx.DiGraph()
    G.add_node("model:demo.wizard", node_type="Model")
    for xml_id, active in (("demo.rule_active", True), ("demo.rule_inactive", False)):
        G.add_node(f"rule:{xml_id}", node_type="Rule", xml_id=xml_id, name=xml_id, domain_force="[]",
                   perm_read=True, perm_write=True, perm_create=True, perm_unlink=True, active=active)
        G.add_edge("model:demo.wizard", f"rule:{xml_id}", edge_type="RESTRICTED_BY")
    return G


def test_xml_declared_acl_is_extracted(tmp_path):
    xml = tmp_path / "security.xml"
    xml.write_text(SECURITY_XML, encoding="utf-8")
    (entry,) = parse_access_entries_from_xml(xml)
    assert (entry.xml_id, entry.model_id, entry.group_id) == ("access_wizard", "model_demo_wizard", "base.group_user")
    assert (entry.perm_read, entry.perm_write, entry.perm_create, entry.perm_unlink) == (True, True, False, False)
    assert entry.all_authenticated is False and entry.lineno == 3


def test_inactive_rule_is_parsed_and_kept_in_graph_with_active_flag(tmp_path):
    xml = tmp_path / "security.xml"
    xml.write_text(SECURITY_XML, encoding="utf-8")
    module = ParsedModule(manifest=_Manifest())
    module.rules = parse_ir_rules_from_xml(xml)
    modules = {"demo": module}
    G = nx.DiGraph()
    add_security_group_nodes(G, build_module_symbol_registry(modules), modules, lambda _d: False)
    assert G.nodes["rule:demo.rule_active"]["active"] is True
    assert G.nodes["rule:demo.rule_inactive"]["active"] is False


def test_acl_xml_id_already_prefixed_is_not_prefixed_twice(tmp_path):
    module = ParsedModule(manifest=_Manifest())
    module.acl_entries = [
        OdooAccessEntry(xml_id="demo.access_a", filepath="x.csv", lineno=2, model_id="model_demo_wizard", perm_read=True),
        OdooAccessEntry(xml_id="access_b", filepath="x.csv", lineno=3, model_id="model_demo_wizard", perm_read=True),
    ]
    modules = {"demo": module}
    G = nx.DiGraph()
    add_security_group_nodes(G, build_module_symbol_registry(modules), modules, lambda _d: False)
    assert "acl:demo.access_a" in G and "acl:demo.demo.access_a" not in G
    assert "acl:demo.access_b" in G


def test_evaluators_ignore_inactive_rules():
    G = _graph_with_rules()
    _groups, _all_auth, rules, _inh = _eval_single_permission(G, "demo.wizard", "read")
    assert [r.rule_xml_id for r in rules] == ["demo.rule_active"]
    result = evaluate_record_rules(G, "demo.wizard", "read", user_groups=[])
    assert [r.rule_xml_id for r in result.applied_global_rules] == ["demo.rule_active"]


def test_old_graph_without_active_attribute_still_enforces_rules():
    G = _graph_with_rules()
    for node in G.nodes.values():
        node.pop("active", None)
    _g, _a, rules, _i = _eval_single_permission(G, "demo.wizard", "read")
    assert len(rules) == 2
