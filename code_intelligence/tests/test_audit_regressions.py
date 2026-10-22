
import networkx as nx

from code_intelligence.agent.tools.execution import _override_user_groups_arg
from code_intelligence.agent.tools.introspection import (
    _explain_decision_path_impl,
    read_precise_source_code,
    resolve_technical_name_to_role,
)
from code_intelligence.graph.loader import (
    _configured_addon_roots,
    _discover_installed_core_modules,
    _discover_installed_source_modules,
    _resolve_addon_roots_for_inventory,
)
from code_intelligence.rules.button_path import button_execution_path
from code_intelligence.rules.data_constraints import _compose_data_constraints_summary
from code_intelligence.rules.navigation import search_dynamic_view_or_menus
from code_intelligence.rules.record_rules import evaluate_record_rules


def test_decision_path_rejects_unknown_nodes_and_missing_edges():
    graph = nx.DiGraph()
    graph.add_node("model:sale.order", node_type="Model")
    graph.add_node("rule:sale_rule", node_type="Rule")

    assert "unknown graph node" in _explain_decision_path_impl(
        graph, ["model:missing", "rule:sale_rule"]
    )
    assert "no graph edge exists" in _explain_decision_path_impl(
        graph, ["model:sale.order", "rule:sale_rule"]
    )


def test_record_rules_abstain_when_requester_groups_are_unknown():
    graph = nx.DiGraph()
    graph.add_node("model:sale.order", node_type="Model")

    result = evaluate_record_rules(
        graph, "sale.order", permission="read", user_groups=None
    )

    assert "membership is unresolved" in result.summary_text
    assert "No conclusion" in result.summary_text
    assert result.evidence == []


def test_failed_semgrep_scan_is_not_reported_as_no_constraints():
    summary = _compose_data_constraints_summary(
        "purchase.order.line", [], ["Semgrep executable unavailable"]
    )

    assert "incomplete" in summary
    assert "No conclusion" in summary
    assert "No _sql_constraints" not in summary


def test_unknown_group_role_is_not_fabricated_from_technical_slug():
    assert resolve_technical_name_to_role("custom.group_special_approver") == (
        "Unknown role (custom.group_special_approver)"
    )


def test_addon_roots_follow_odoo_conf_order_and_resolve_relative_paths(tmp_path, monkeypatch):
    first_root = tmp_path / "custom"
    second_root = tmp_path / "core"
    first_root.mkdir()
    second_root.mkdir()
    config_file = tmp_path / "odoo.conf"
    config_file.write_text(
        "[options]\naddons_path = custom, core\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    roots = _configured_addon_roots(config_file, [second_root, first_root])

    assert roots == [first_root.resolve(), second_root.resolve()]


def test_addon_roots_use_explicit_fallback_when_odoo_conf_is_unavailable(tmp_path):
    fallback_roots = [tmp_path / "core", tmp_path / "custom"]

    roots = _configured_addon_roots(tmp_path / "missing.conf", fallback_roots)

    assert roots == [path.resolve() for path in fallback_roots]


def test_installed_module_source_uses_first_configured_root(tmp_path):
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    for root in (first_root, second_root):
        module = root / "shared_module"
        module.mkdir(parents=True)
        (module / "__manifest__.py").write_text("{}", encoding="utf-8")

    modules = _discover_installed_source_modules(
        [first_root, second_root], [{"name": "shared_module"}]
    )

    assert modules["shared_module"] == first_root / "shared_module"


def test_source_reader_rejects_files_outside_addon_roots(tmp_path, monkeypatch):
    import config.settings as settings

    addon_root = tmp_path / "addons"
    addon_root.mkdir()
    outside_file = tmp_path / "secrets.py"
    outside_file.write_text("secret = True\n", encoding="utf-8")
    monkeypatch.setattr(settings, "CORE_ADDONS_PATH", str(addon_root))
    monkeypatch.setattr(settings, "CUSTOM_ADDONS_PATH", None)
    monkeypatch.setattr(settings, "OCA_SAMPLE_ADDONS_PATH", None)

    result = read_precise_source_code(str(outside_file), 1, 1)

    assert result.startswith("Error:")
    assert "outside configured addon roots" in result


def test_button_path_rejects_multiple_exact_workflow_methods():
    graph = nx.DiGraph()
    graph.add_node("model:sale.order", node_type="Model")
    for state in ("draft", "sent", "done", "cancel"):
        graph.add_node(
            f"state:sale.order.{state}",
            node_type="State",
            model="sale.order",
            state_value=state,
        )
    graph.add_edge(
        "state:sale.order.draft",
        "state:sale.order.sent",
        edge_type="TRANSITIONS_VIA",
        button_transitions=[{"method_name": "action_confirm", "label_bouton": "Confirm"}],
    )
    graph.add_edge(
        "state:sale.order.cancel",
        "state:sale.order.done",
        edge_type="TRANSITIONS_VIA",
        button_transitions=[{"method_name": "button_confirm", "label_bouton": "Confirm"}],
    )

    result = button_execution_path(graph, "Confirm", "sale.order")

    assert "is ambiguous" in result.summary_text
    assert "action_confirm" in result.summary_text
    assert "button_confirm" in result.summary_text
    assert result.method_name == ""


def test_view_hook_presence_does_not_prove_dynamic_button_injection():
    graph = nx.DiGraph()
    graph.add_node(
        "method:sale.order.get_view",
        node_type="Method",
        name="get_view",
        filepath="",
        lineno=1,
        override_sites=[],
    )

    result = search_dynamic_view_or_menus(graph, "sale.order", "Special Button")

    assert result is not None
    assert "has not been verified to inject this button" in result.summary_text
    assert "Dynamic View Injection Detected" not in result.summary_text
    assert result.evidence == []


def test_dispatch_does_not_turn_incomplete_group_resolution_into_empty_groups():
    args = {"model_name": "sale.order", "user_groups_json": "[]"}

    result = _override_user_groups_arg(
        "evaluate_record_rules",
        args,
        ["sale.group_sale_salesman"],
        requester_groups_known=False,
    )

    assert result["user_groups_json"] == "null"


def test_addon_roots_use_odoo_defaults_when_config_omits_addons_path(tmp_path):
    config_file = tmp_path / "odoo.conf"
    config_file.write_text("[options]\nhttp_port = 8069\n", encoding="utf-8")
    default_roots = [tmp_path / "odoo" / "addons", tmp_path / "addons"]
    fallback_roots = [tmp_path / "custom"]

    roots = _configured_addon_roots(config_file, fallback_roots, default_roots)

    assert roots == [path.resolve() for path in default_roots]


def test_empty_installed_core_inventory_does_not_load_uninstalled_candidates():
    assert _discover_installed_core_modules(
        ["account", "sale", "purchase"],
        installed_modules=[],
    ) == []


def test_live_inventory_without_odoo_config_skips_fallback_addon_roots(tmp_path):
    fallback_roots = [tmp_path / "core", tmp_path / "custom"]

    roots = _resolve_addon_roots_for_inventory(
        tmp_path / "missing.conf",
        fallback_roots,
        fallback_roots[:1],
        installed_modules=[],
    )

    assert roots == []


def test_offline_inventory_without_odoo_config_uses_explicit_fallback(tmp_path):
    fallback_roots = [tmp_path / "core", tmp_path / "custom"]

    roots = _resolve_addon_roots_for_inventory(
        tmp_path / "missing.conf",
        fallback_roots,
        fallback_roots[:1],
        installed_modules=None,
    )

    assert roots == [path.resolve() for path in fallback_roots]


def test_invalid_odoo_config_with_live_inventory_skips_addon_roots(tmp_path):
    config_file = tmp_path / "odoo.conf"
    config_file.write_text("[options\naddons_path = /guessed/path\n", encoding="utf-8")
    fallback_roots = [tmp_path / "core", tmp_path / "custom"]

    roots = _resolve_addon_roots_for_inventory(
        config_file,
        fallback_roots,
        fallback_roots[:1],
        installed_modules=[{"name": "sale", "state": "installed"}],
    )

    assert roots == []


def test_invalid_odoo_config_without_live_inventory_uses_explicit_fallback(tmp_path):
    config_file = tmp_path / "odoo.conf"
    config_file.write_text("[options\naddons_path = /guessed/path\n", encoding="utf-8")
    fallback_roots = [tmp_path / "core", tmp_path / "custom"]

    roots = _resolve_addon_roots_for_inventory(
        config_file,
        fallback_roots,
        fallback_roots[:1],
        installed_modules=None,
    )

    assert roots == [path.resolve() for path in fallback_roots]
