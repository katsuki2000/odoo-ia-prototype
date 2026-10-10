from types import SimpleNamespace

import pytest

import code_intelligence.graph.loader as loader


def test_source_module_discovery_respects_first_configured_addon_root(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    for root, marker in ((first, "first"), (second, "second")):
        module = root / "same_module"
        module.mkdir(parents=True)
        (module / "__manifest__.py").write_text("{'name': 'same'}")
        (module / "marker.txt").write_text(marker)

    discovered = loader._discover_installed_source_modules(
        [first, second],
        [{"name": "same_module", "state": "installed"}],
    )

    assert discovered["same_module"] == first / "same_module"


def test_core_candidates_are_not_assumed_installed_when_inventory_is_empty():
    assert loader._discover_installed_core_modules(
        loader.CORE_MODULE_CANDIDATES,
        installed_modules=[],
    ) == []


def test_cached_graph_must_match_current_installed_module_versions():
    graph = SimpleNamespace(graph={
        "instance_fingerprint_data": {
            "modules": [
                ["sale", "17.0.1.0", "installed"],
                ["base", "17.0.1.0", "installed"],
            ]
        }
    })
    installed = [
        {"name": "base", "installed_version": "17.0.1.0", "state": "installed"},
        {"name": "sale", "installed_version": "17.0.1.0", "state": "installed"},
    ]
    assert loader._graph_matches_installed_inventory(graph, installed)
    assert not loader._graph_matches_installed_inventory(
        graph, installed + [{"name": "purchase", "installed_version": "17.0.1.0", "state": "installed"}]
    )
    assert not loader._graph_matches_installed_inventory(
        graph, [{"name": "sale", "installed_version": "17.0.2.0", "state": "installed"}]
    )
    assert not loader._graph_matches_installed_inventory(graph, None)


def test_graph_build_refuses_unknown_install_state_outside_explicit_offline_mode(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "GRAPH_OFFLINE_MODE", False)
    monkeypatch.setattr(loader, "_read_runtime_module_inventory", lambda: None)

    with pytest.raises(RuntimeError, match="installed-module inventory is unavailable"):
        loader.get_code_intelligence_graph(force_rebuild=True)
