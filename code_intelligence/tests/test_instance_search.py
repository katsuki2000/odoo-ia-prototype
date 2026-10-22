import networkx as nx
import pytest

from code_intelligence.agent.tools.instance_search import find_instance_candidates
from code_intelligence.agent.resolution.semantic_retrieval import SEMANTIC_RETRIEVAL_ENABLED_ENV


@pytest.fixture(autouse=True)
def no_semantic_retrieval(monkeypatch):
    monkeypatch.setenv(SEMANTIC_RETRIEVAL_ENABLED_ENV, "false")


@pytest.fixture
def graph():
    graph = nx.DiGraph()
    graph.add_node("model:custom.asset.loan", node_type="Model", name="custom.asset.loan",
                   description="Mise a disposition de materiel")
    graph.add_node("model:hr.contract", node_type="Model", name="hr.contract",
                   description="Contrat employ\u00e9")
    return graph


def _scores(result):
    return {item["node_id"]: item["score"] for item in result["candidates"]}


def test_accented_and_unaccented_query_score_the_same(graph):
    accented = find_instance_candidates(graph, "mise \u00e0 disposition de mat\u00e9riel")
    plain = find_instance_candidates(graph, "mise a disposition de materiel")
    assert _scores(accented) == _scores(plain)
    assert accented["candidates"][0]["node_id"] == "model:custom.asset.loan"


def test_unaccented_query_finds_an_accented_label(graph):
    result = find_instance_candidates(graph, "contrat employe")
    assert result["candidates"][0]["node_id"] == "model:hr.contract"
    assert _scores(result)["model:hr.contract"] == _scores(find_instance_candidates(graph, "contrat employ\u00e9"))["model:hr.contract"]


def test_returned_labels_keep_their_original_spelling(graph):
    result = find_instance_candidates(graph, "contrat employe")
    assert result["candidates"][0]["labels"] == ["Contrat employ\u00e9"]
