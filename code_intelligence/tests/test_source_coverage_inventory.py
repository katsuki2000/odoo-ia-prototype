from pathlib import Path

import networkx as nx

from code_intelligence.agent.tools.source_search import SearchLimits, search_source_fragments
from code_intelligence.graph.loader import (
    _build_coverage_gaps,
    _build_source_file_inventory,
)


def test_source_inventory_includes_helpers_views_and_client_code(tmp_path):
    module = tmp_path / "custom_request"
    (module / "models").mkdir(parents=True)
    (module / "views").mkdir()
    (module / "static" / "src" / "js").mkdir(parents=True)
    (module / "tests").mkdir()
    (module / "demo").mkdir()
    (module / "models" / "approval_helper.py").write_text(
        "def check_approval(amount):\n    return amount > 5000\n",
        encoding="utf-8",
    )
    (module / "views" / "request_form.xml").write_text("<form/>", encoding="utf-8")
    (module / "static" / "src" / "js" / "request.js").write_text(
        "console.log('request');\n", encoding="utf-8",
    )
    (module / "tests" / "test_helper.py").write_text("def test_only(): pass\n", encoding="utf-8")
    (module / "demo" / "demo.xml").write_text("<odoo/>", encoding="utf-8")

    entries, failures = _build_source_file_inventory({"custom_request": module})
    indexed = {Path(item["filepath"]).relative_to(module).as_posix() for item in entries}

    assert failures == []
    assert "models/approval_helper.py" in indexed
    assert "views/request_form.xml" in indexed
    assert "static/src/js/request.js" in indexed
    assert "tests/test_helper.py" not in indexed
    assert "demo/demo.xml" not in indexed
    assert all(item["module"] == "custom_request" for item in entries)


def test_source_search_finds_module_files_without_graph_nodes(tmp_path):
    addons = tmp_path / "addons"
    module = addons / "custom_request"
    helper = module / "models" / "approval_helper.py"
    helper.parent.mkdir(parents=True)
    helper.write_text(
        "def check_approval(amount):\n"
        "    if amount > 5000:\n"
        "        raise ValueError('Approval required before confirmation')\n",
        encoding="utf-8",
    )

    graph = nx.DiGraph()
    graph.add_node(
        "model:custom.request",
        node_type="Model",
        name="custom.request",
        filepaths=[],
    )
    graph.add_node("module:custom_request", node_type="Module", name="custom_request")
    graph.add_edge("model:custom.request", "module:custom_request", edge_type="DEFINED_IN")
    graph.graph["source_file_inventory_version"] = 1
    graph.graph["source_file_inventory"] = [
        {"filepath": str(helper.resolve()), "module": "custom_request"},
    ]
    graph.graph["coverage_gaps"] = {}

    result = search_source_fragments(
        graph,
        [addons],
        "approval confirmation",
        model="custom.request",
        limits=SearchLimits(
            max_files=10,
            max_file_bytes=20_000,
            max_total_bytes=100_000,
            max_fragments=10,
            max_lines=16,
        ),
    )

    assert result["coverage_metadata_valid"] is True
    assert result["complete_scan"] is True
    assert result["candidates"]
    assert result["candidates"][0]["filepath"] == str(helper.resolve())
    assert result["candidates"][0]["modules"] == ["custom_request"]


def test_legacy_graph_without_coverage_metadata_never_claims_complete_scan(tmp_path):
    addons = tmp_path / "addons"
    source = addons / "custom_request" / "models" / "request.py"
    source.parent.mkdir(parents=True)
    source.write_text("def action_confirm():\n    raise ValueError('approval required')\n", encoding="utf-8")

    graph = nx.DiGraph()
    graph.add_node(
        "model:custom.request",
        node_type="Model",
        name="custom.request",
        filepaths=[str(source.resolve())],
    )

    result = search_source_fragments(graph, [addons], "approval required")

    assert result["coverage_metadata_valid"] is False
    assert result["complete_scan"] is False
    assert result["candidates"]


def test_coverage_report_marks_unavailable_inventory_and_missing_sources(tmp_path):
    addons = tmp_path / "addons"
    addons.mkdir()
    incomplete = _build_coverage_gaps(
        installed_modules=None,
        addon_roots=[addons],
        installed_source_modules={},
        loaded_module_directories={},
    )
    assert incomplete["runtime_module_inventory_unavailable"] is True

    complete = _build_coverage_gaps(
        installed_modules=[{"name": "base"}, {"name": "custom_request"}],
        addon_roots=[addons],
        installed_source_modules={"base": addons / "base", "custom_request": addons / "custom_request"},
        loaded_module_directories={"base": addons / "base", "custom_request": addons / "custom_request"},
    )
    assert complete == {}

    missing_source = _build_coverage_gaps(
        installed_modules=[{"name": "base"}, {"name": "custom_request"}],
        addon_roots=[addons],
        installed_source_modules={"base": addons / "base"},
        loaded_module_directories={"base": addons / "base"},
    )
    assert missing_source["installed_modules_without_source"] == ["custom_request"]
