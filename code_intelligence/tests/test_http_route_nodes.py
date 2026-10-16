"""Section 1418: @http.route methods are extracted with ast and become HttpRoute nodes; the audit inventory agrees."""
import networkx as nx

from code_intelligence.evaluation.source_inventory import inventory_module
from code_intelligence.extractor.http_routes import parse_http_routes
from code_intelligence.graph.nodes import ParsedModule
from code_intelligence.graph.output_nodes import add_http_route_nodes

CONTROLLER = '''
from odoo import http
from odoo.http import route


class PortalController(http.Controller):

    @http.route(['/my/orders', '/my/orders/page/<int:page>'], type='http', auth="public", website=True)
    def orders(self, **kw):
        return ""

    @http.route('/my/orders/<int:order_id>/decline', type='http', auth='user', methods=['POST'], csrf=False)
    def decline(self, order_id):
        return ""

    @route("/my/default")
    def default_auth(self):
        return ""

    @http.route(PATH_CONSTANT, auth=AUTH_CONSTANT)
    def dynamic(self):
        return ""

    def not_a_route(self):
        return ""


class PortalOverride(PortalController):

    @http.route()
    def orders(self, **kw):
        return super().orders(**kw)
'''


class _Manifest:
    depends = []
    filepath = "demo/__manifest__.py"


def _write_module(tmp_path):
    module_dir = tmp_path / "demo"
    (module_dir / "controllers").mkdir(parents=True)
    (module_dir / "controllers" / "main.py").write_text(CONTROLLER, encoding="utf-8")
    return module_dir


def test_routes_are_extracted_with_declared_arguments(tmp_path):
    routes = {(r.controller, r.method_name): r for r in parse_http_routes(_write_module(tmp_path) / "controllers" / "main.py")}
    assert len(routes) == 5
    orders = routes[("PortalController", "orders")]
    assert orders.paths == ["/my/orders", "/my/orders/page/<int:page>"]
    assert (orders.route_type, orders.auth, orders.website, orders.overrides_parent) == ("http", "public", True, False)
    decline = routes[("PortalController", "decline")]
    assert (decline.methods, decline.csrf, decline.auth) == (["POST"], False, "user")
    assert routes[("PortalController", "default_auth")].auth == "user"  # Odoo default, path declared without auth


def test_non_literal_arguments_are_left_empty_and_bare_route_is_an_override(tmp_path):
    routes = {(r.controller, r.method_name): r for r in parse_http_routes(_write_module(tmp_path) / "controllers" / "main.py")}
    dynamic = routes[("PortalController", "dynamic")]
    assert dynamic.paths == [] and dynamic.auth == ""
    override = routes[("PortalOverride", "orders")]
    assert override.overrides_parent is True and override.paths == [] and override.auth == ""


def test_nodes_are_built_and_inventory_agrees(tmp_path):
    module_dir = _write_module(tmp_path)
    module = ParsedModule(manifest=_Manifest())
    module.http_routes = parse_http_routes(module_dir / "controllers" / "main.py")
    G = nx.DiGraph()
    add_http_route_nodes(G, {"demo": module})
    node = G.nodes["route:demo.PortalController.orders"]
    assert node["node_type"] == "HttpRoute" and node["technical_tags"] == ["http_route"] and node["module"] == "demo"
    graph_ids = {n.partition(":")[2] for n, d in G.nodes(data=True) if d["node_type"] == "HttpRoute"}
    assert graph_ids == inventory_module(module_dir).xmlIds["http_route"]


def test_controller_declared_inside_a_function_is_not_a_route_for_extractor_nor_inventory(tmp_path):
    module_dir = tmp_path / "demo"
    module_dir.mkdir()
    source = (
        "from odoo import http\n"
        "def build():\n"
        "    class Dummy(http.Controller):\n"
        "        @http.route('/x')\n"
        "        def wait(self): pass\n"
    )
    (module_dir / "tests.py").write_text(source, encoding="utf-8")
    assert parse_http_routes(module_dir / "tests.py") == []
    assert inventory_module(module_dir).xmlIds["http_route"] == set()
