import networkx as nx

from api import main


def test_warm_up_loads_the_graph(monkeypatch):
    graph = nx.DiGraph()
    graph.graph["translation_languages"] = ["fr"]
    calls = []
    monkeypatch.setattr(
        "code_intelligence.graph.loader.get_code_intelligence_graph",
        lambda **kwargs: calls.append(kwargs) or graph,
    )
    main.warm_up_code_intelligence_graph()
    assert calls == [{}]


def test_warm_up_failure_does_not_stop_the_api(monkeypatch):
    def failing(**_kwargs):
        raise RuntimeError("odoo unreachable")

    monkeypatch.setattr("code_intelligence.graph.loader.get_code_intelligence_graph", failing)
    main.warm_up_code_intelligence_graph()
