"""Section 1417: ir.actions.report and mail.template are extracted, merged across modules and linked in the graph."""
import networkx as nx

from code_intelligence.extractor.xml import parse_mail_templates_from_xml, parse_reports_from_xml
from code_intelligence.graph.integrity_report import EDGE_TYPES
from code_intelligence.graph.nodes import ParsedModule
from code_intelligence.graph.output_nodes import add_report_and_template_nodes

BASE_XML = """<?xml version="1.0"?>
<odoo>
  <record id="action_report_order" model="ir.actions.report">
    <field name="name">Quotation / Order</field>
    <field name="model">demo.order</field>
    <field name="report_type">qweb-pdf</field>
    <field name="report_name">demo.report_order</field>
    <field name="print_report_name">'Order - %s' % (object.name)</field>
    <field name="binding_model_id" ref="model_demo_order"/>
  </record>
  <record id="action_report_proforma" model="ir.actions.report">
    <field name="name">Pro-forma</field>
    <field name="model">demo.order</field>
    <field name="report_name">demo.report_proforma</field>
    <field name="groups_id" eval="[(4, ref('demo.group_proforma'))]"/>
  </record>
  <record id="email_template_order" model="mail.template">
    <field name="name">Send Quotation</field>
    <field name="model_id" ref="demo.model_demo_order"/>
    <field name="subject">Order {{ object.name }}</field>
    <field name="report_template_ids" eval="[(4, ref('action_report_order'))]"/>
    <field name="body_html" type="html"><p>Hello</p></field>
  </record>
</odoo>
"""
OVERRIDE_XML = """<?xml version="1.0"?>
<odoo>
  <record id="demo.action_report_order" model="ir.actions.report">
    <field name="groups_id" eval="[(4, ref('demo_pro.group_manager'))]"/>
  </record>
  <record id="demo.email_template_order" model="mail.template">
    <field name="active">0</field>
  </record>
</odoo>
"""


class _Manifest:
    depends = []
    filepath = "demo/__manifest__.py"


class _Registry:
    models = {"demo.order": []}

    def resolve_model_ref_or_record(self, ref, module, filepath):
        return "demo.order" if ref.endswith("model_demo_order") else None


def _modules(tmp_path):
    base, extra = tmp_path / "base.xml", tmp_path / "extra.xml"
    base.write_text(BASE_XML, encoding="utf-8")
    extra.write_text(OVERRIDE_XML, encoding="utf-8")
    demo, demo_pro = ParsedModule(manifest=_Manifest()), ParsedModule(manifest=_Manifest())
    demo.reports, demo.mail_templates = parse_reports_from_xml(base), parse_mail_templates_from_xml(base)
    demo_pro.reports, demo_pro.mail_templates = parse_reports_from_xml(extra), parse_mail_templates_from_xml(extra)
    return {"demo": demo, "demo_pro": demo_pro}


def test_report_and_template_fields_are_extracted(tmp_path):
    modules = _modules(tmp_path)
    order, proforma = modules["demo"].reports
    assert (order.model, order.report_type, order.report_name, order.binding_model_id) == (
        "demo.order", "qweb-pdf", "demo.report_order", "model_demo_order")
    assert proforma.groups_id == ["demo.group_proforma"]
    (template,) = modules["demo"].mail_templates
    assert (template.model_id, template.subject, template.report_template_ids) == (
        "demo.model_demo_order", "Order {{ object.name }}", ["action_report_order"])
    assert not hasattr(template, "body_html")


def test_nodes_and_edges_are_built(tmp_path):
    G = nx.DiGraph()
    add_report_and_template_nodes(G, _Registry(), _modules(tmp_path))
    assert G.nodes["report:demo.action_report_order"]["target_model"] == "demo.order"
    # Node kinds are carried by node_type; TechnicalTag stays the architecture.md vocabulary (record_rule, acl...).
    assert G.nodes["report:demo.action_report_order"]["technical_tags"] == []
    assert G.nodes["mail_template:demo.email_template_order"]["technical_tags"] == []
    edges = {(s, t, d["edge_type"]) for s, t, d in G.edges(data=True)}
    assert ("report:demo.action_report_order", "model:demo.order", "REPORTS_ON") in edges
    assert ("report:demo.action_report_proforma", "group:demo.group_proforma", "APPLIES_TO_GROUP") in edges
    assert ("mail_template:demo.email_template_order", "model:demo.order", "TEMPLATE_FOR") in edges
    assert ("mail_template:demo.email_template_order", "report:demo.action_report_order", "ATTACHES_REPORT") in edges
    assert {"REPORTS_ON", "TEMPLATE_FOR", "ATTACHES_REPORT"} <= set(EDGE_TYPES)


def test_override_from_another_module_is_merged_not_duplicated(tmp_path):
    G = nx.DiGraph()
    add_report_and_template_nodes(G, _Registry(), _modules(tmp_path))
    assert [n for n in G if n.startswith("report:")] == ["report:demo.action_report_order", "report:demo.action_report_proforma"]
    order = G.nodes["report:demo.action_report_order"]
    assert order["name"] == "Quotation / Order" and order["report_name"] == "demo.report_order"
    assert ("report:demo.action_report_order", "group:demo_pro.group_manager", "APPLIES_TO_GROUP") in {
        (s, t, d["edge_type"]) for s, t, d in G.edges(data=True)}
    assert G.nodes["mail_template:demo.email_template_order"]["active"] is False
    assert G.nodes["mail_template:demo.email_template_order"]["subject"] == "Order {{ object.name }}"
