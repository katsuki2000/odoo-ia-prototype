"""Client action tags are linked to the models their JS reaches, and the menu then proves the navigation path."""
from pathlib import Path

import networkx as nx

from code_intelligence.extractor.js_client_actions import parse_client_action_models
from code_intelligence.graph.nodes import add_menu_nodes
from code_intelligence.graph.symbols import build_module_symbol_registry
from code_intelligence.rules.common import QueryStatus
from code_intelligence.rules.navigation import describe_navigation_path
from code_intelligence.tests.test_client_action_navigation import _module


def _write(root: Path, relative: str, content: str) -> None:
    path = root / "static" / "src" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _addon(tmp_path: Path) -> Path:
    addon = tmp_path / "dash"
    _write(addon, "action/action.js", """
import { registry } from "@web/core/registry";
import { Loader } from "./loader";
import { helper } from "@dash/shared/helper";
import { other } from "@web/core/other";
registry
    .category("actions")
    .add("action_dashboard", Action, { force: true });
""")
    _write(addon, "action/loader.js", """
import { Action } from "./action";
export class Loader {
    async groups() { return this.orm.webSearchRead("dash.group", []); }
    async board() { return this.env.services.orm.call("dash.board", "read", []); }
    async drop() { return this.orm.create("dash.created", {}); }
    async dynamic() { return this.orm.call(this.model, "read", []); }
    // async old() { return this.orm.call("dash.commented", "read", []); }
    /* this.orm.read("dash.block_commented", []); */
}
""")
    _write(addon, "shared/helper.js", 'export const helper = (orm) => orm.silent.searchRead("dash.shared", []);\n')
    _write(addon, "unrelated/standalone.js", 'export const x = (orm) => orm.read("dash.unrelated", []);\n')
    _write(addon, "lazy/loader.js", """
import { registry } from "@web/core/registry";
const actionRegistry = registry.category("actions");
actionRegistry.add("action_lazy", () => ({}));
""")
    return addon


def test_tag_maps_to_literal_models_reached_through_local_imports(tmp_path):
    models = parse_client_action_models(_addon(tmp_path))
    assert models["action_dashboard"] == ["dash.board", "dash.group", "dash.shared"]


def test_registration_through_registry_alias_is_found_without_models(tmp_path):
    assert parse_client_action_models(_addon(tmp_path))["action_lazy"] == []


def test_addon_without_sources_has_no_client_actions(tmp_path):
    assert parse_client_action_models(tmp_path) == {}


def _graph(tmp_path):
    module = _module(tmp_path)
    module.client_action_models = {"action_dashboard": ["dash.board", "dash.group", "dash.missing"]}
    modules = {"dash": module}
    G = nx.DiGraph()
    G.add_node("model:dash.board", node_type="Model")
    G.add_node("model:dash.group", node_type="Model")
    add_menu_nodes(G, build_module_symbol_registry(modules), modules)
    return G


def test_client_action_menu_opens_existing_models_only(tmp_path):
    G = _graph(tmp_path)
    opened = {v: e["via"] for _, v, e in G.out_edges("menu:dash.menu_root", data=True) if e["edge_type"] == "OPENS_MODEL"}
    assert opened == {"model:dash.board": "client_action_js", "model:dash.group": "client_action_js"}
    assert "model:dash.missing" not in G


def test_navigation_path_is_found_and_lists_every_label(tmp_path):
    G = _graph(tmp_path)
    G.nodes["menu:dash.menu_root"]["business_labels"] = [{"label": "Tableaux de bord", "language": "fr"}]
    result = describe_navigation_path(G, "dash.board")
    assert result.status == QueryStatus.FOUND
    assert result.menu_breadcrumb == ["Dashboards / Tableaux de bord"]
    assert "ne prouve pas" not in result.summary_text
