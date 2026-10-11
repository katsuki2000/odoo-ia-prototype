import importlib.util
from pathlib import Path

import networkx as nx

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "rebuild_graph.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("rebuild_graph_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _graph(runtime_inventory_available):
    graph = nx.DiGraph()
    graph.add_node("model:a", node_type="Model", technical_tags=["x"])
    graph.graph["instance_fingerprint_data"] = {
        "runtime_inventory_available": runtime_inventory_available,
        "modules": [],
    }
    return graph


def _run(monkeypatch, tmp_path, runtime_inventory_available, argv=()):
    module = _load_script()
    target = tmp_path / "active_graph.json"
    target.write_text("GOOD", encoding="utf-8")

    def fake_build(**_kwargs):
        target.write_text("NEW", encoding="utf-8")
        return _graph(runtime_inventory_available)

    monkeypatch.setattr(module, "GRAPH_JSON_PATH", target)
    monkeypatch.setattr(module, "get_code_intelligence_graph", fake_build)
    return module.main(list(argv)), target


def test_degraded_graph_is_refused_and_the_previous_one_restored(monkeypatch, tmp_path):
    code, target = _run(monkeypatch, tmp_path, runtime_inventory_available=False)
    assert code == 2
    assert target.read_text(encoding="utf-8") == "GOOD"


def test_degraded_graph_is_kept_with_allow_offline(monkeypatch, tmp_path):
    code, target = _run(monkeypatch, tmp_path, False, argv=["--allow-offline"])
    assert code == 0
    assert target.read_text(encoding="utf-8") == "NEW"


def test_runtime_backed_graph_replaces_the_previous_one(monkeypatch, tmp_path):
    code, target = _run(monkeypatch, tmp_path, runtime_inventory_available=True)
    assert code == 0
    assert target.read_text(encoding="utf-8") == "NEW"
