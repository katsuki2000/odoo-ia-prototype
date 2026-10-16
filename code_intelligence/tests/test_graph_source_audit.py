"""The audit compares module sources with graph nodes and reports what the graph does not keep."""
from pathlib import Path

import networkx as nx

from code_intelligence.evaluation.graph_source_audit import build_source_audit
from code_intelligence.evaluation.source_inventory import inventory_module

MANIFEST = "{'name': 'dash'}\n"
VIEWS_XML = """<odoo>
  <record id="group_manager" model="res.groups"><field name="name">Manager</field></record>
  <record id="group_user" model="res.groups"><field name="name">User</field></record>
  <record id="cron_sync" model="ir.cron"/>
  <record id="main_view" model="ir.ui.view"/>
  <record id="mail_tpl" model="mail.template"/>
  <menuitem id="menu_root" name="Dash"/>
  <template id="page"><div/></template>
</odoo>
"""
CONTROLLER = """
from odoo import http
class Main(http.Controller):
    @http.route('/dash', auth='user')
    def index(self): return ''
    @route('/dash/other')
    def other(self): return ''
    def helper(self): return ''
"""
OWL_XML = '<templates><t t-name="dash.Widget"><div/></t></templates>'
ACCESS_CSV = "id,name,model_id:id\naccess_board,board,model_dash_board\n"
ACTION_JS = 'registry.category("actions").add("action_dash", Action);\n'


def _module(tmp_path: Path) -> Path:
    root = tmp_path / "dash"
    files = {
        "__manifest__.py": MANIFEST,
        "views/views.xml": VIEWS_XML,
        "controllers/main.py": CONTROLLER,
        "security/ir.model.access.csv": ACCESS_CSV,
        "static/src/widget.xml": OWL_XML,
        "static/src/action.js": ACTION_JS,
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def test_inventory_counts_every_kind_and_qualifies_xml_ids(tmp_path):
    inventory = inventory_module(_module(tmp_path))
    assert inventory.xmlIds["res.groups"] == {"dash.group_manager", "dash.group_user"}
    assert inventory.xmlIds["ir.ui.menu"] == {"dash.menu_root"}
    assert inventory.xmlIds["ir.model.access"] == {"dash.access_board"}
    assert inventory.xmlIds["js_client_action_tag"] == {"action_dash"}
    counts = inventory.counts
    assert (counts["http_route"], counts["owl_template"], counts["js_file"]) == (2, 1, 1)
    assert (counts["qweb_template"], counts["mail.template"], counts["ir.ui.view"]) == (1, 1, 1)


def _graph(tmp_path: Path, groups=("dash.group_manager",)) -> nx.DiGraph:
    G = nx.DiGraph()
    G.add_node("module:dash", node_type="Module", name="dash", filepath=str(_module(tmp_path) / "__manifest__.py"))
    G.add_node("module:ghost", node_type="Module", name="ghost", filepath=str(tmp_path / "ghost" / "__manifest__.py"))
    for xmlId in groups:
        G.add_node(f"group:{xmlId}", node_type="Group", xml_id=xmlId)
    G.add_node("menu:dash.menu_root", node_type="Menu", xml_id="dash.menu_root")
    G.add_node("server_action:dash.cron_sync", node_type="ServerAction", xml_id="dash.cron_sync")
    G.add_node("acl:dash.access_board", node_type="AccessEntry")
    G.add_node("group:dash.stale", node_type="Group", xml_id="dash.stale")
    return G


def _rows(report):
    return {row["kind"]: row for row in report["kinds"]}


def test_audit_reports_missing_and_extra_nodes(tmp_path):
    report = build_source_audit(_graph(tmp_path))
    rows = _rows(report)
    assert rows["Group"]["status"] == "partial"
    assert (rows["Group"]["disk"], rows["Group"]["missing"], rows["Group"]["extra"]) == (2, 1, 1)
    assert rows["Group"]["missing_examples"] == ["dash.group_user"]
    for kind in ("Menu", "ServerAction", "AccessEntry"):
        assert rows[kind]["status"] == "covered", kind


def test_audit_separates_attribute_only_and_unextracted_kinds(tmp_path):
    rows = _rows(build_source_audit(_graph(tmp_path)))
    assert rows["ir.ui.view"]["status"] == "attribute_only"
    assert rows["js_client_action_tag"]["disk"] == 1
    for kind, count in (("qweb_template", 1), ("owl_template", 1)):
        assert (rows[kind]["status"], rows[kind]["disk"]) == ("not_extracted", count), kind
    # Since 1417/1418 mail templates and HTTP routes are node kinds: the fixture graph has none, so all are missing.
    assert (rows["MailTemplate"]["disk"], rows["MailTemplate"]["missing"]) == (1, 1)
    assert (rows["HttpRoute"]["disk"], rows["HttpRoute"]["missing"]) == (2, 2)
    assert rows["HttpRoute"]["missing_examples"] == ["dash.Main.index", "dash.Main.other"]


def test_modules_without_local_source_are_reported_apart(tmp_path):
    report = build_source_audit(_graph(tmp_path))
    assert report["modules_audited"] == 1
    assert report["modules_without_source"] == ["ghost"]
