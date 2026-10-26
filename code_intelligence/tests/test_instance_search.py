import networkx as nx
import pytest

from code_intelligence.agent.resolution.matching import _fuzzy_match_graph
from code_intelligence.agent.tools.instance_search import find_instance_candidates
from config import settings


@pytest.fixture(autouse=True)
def no_semantic_retrieval(monkeypatch):
    monkeypatch.setattr(settings, "RESOLVER_SEMANTIC_RETRIEVAL_ENABLED", False)


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


def test_a_field_label_containing_the_phrase_does_not_tie_with_the_model_carrying_it():
    graph = nx.DiGraph()
    graph.add_node("model:purchase.order", node_type="Model", name="purchase.order",
                   description="Bon de commande fournisseur")
    graph.add_node("model:res.company", node_type="Model", name="res.company", description="Societe")
    graph.add_node("field:res.company.po_lines", node_type="Field", name="po_lines",
                   model="res.company", label="Lignes de bon de commande")
    ranked = _fuzzy_match_graph("bon de commande", graph)
    scores = dict(ranked)
    assert ranked[0][0] == "purchase.order"
    assert scores["purchase.order"] == 100.0
    assert scores["res.company"] < scores["purchase.order"]


def test_returned_labels_keep_their_original_spelling(graph):
    result = find_instance_candidates(graph, "contrat employe")
    assert result["candidates"][0]["labels"] == ["Contrat employ\u00e9"]
