"""
code_intelligence/tests/test_s2_0_business_resolver.py

Unit tests for Business Term Resolver.
Tests exact mention, graph model matching, bounded arbitration and unresolved concept fallback.
No manual alias tables exist anymore (removed, journal 1436-1438).
"""


import pytest
import networkx as nx
from code_intelligence.agent.resolver import resolve_business_term


@pytest.fixture
def mock_graph():
    G = nx.DiGraph()
    G.add_node("model:account.move", node_type="Model", name="account.move")
    G.add_node("model:custom_credit_note_approval", node_type="Model", name="custom_credit_note_approval")
    G.add_node("model:custom_purchase_request", node_type="Model", name="custom_purchase_request")
    G.add_node("model:custom.purchase.request", node_type="Model", name="custom.purchase.request")
    G.add_node("model:custom_asset_loan", node_type="Model", name="custom_asset_loan")
    G.add_node("model:custom.asset.loan", node_type="Model", name="custom.asset.loan")
    G.add_node("model:hr.leave", node_type="Model", name="hr.leave")
    G.add_node("model:custom.reimbursement.request", node_type="Model", name="custom.reimbursement.request")
    G.add_node("module:custom_expense_reimbursement_indirect", node_type="Module", name="custom_expense_reimbursement_indirect")
    G.add_edge("model:custom.reimbursement.request", "module:custom_expense_reimbursement_indirect", edge_type="DEFINED_IN")

    # regression fixture: a Field labeled exactly "avoirs" on an unrelated
    # model (res.partner), mirroring the real bug observed in production
    # ('avoirs' -> fuzzy: res.partner (100.0)). Without this node, the
    # fuzzy index is empty and the ordering bug can never be exercised —
    # the test would pass even if someone reverted the fix.
    G.add_node("model:res.partner", node_type="Model", name="res.partner")
    G.add_node(
        "field:res_partner_avoirs",
        node_type="Field",
        label="avoirs",
        model="res.partner",
    )
    return G


def test_s2_0_exact_module_mention_expense(mock_graph):
    res = resolve_business_term("Qui valide la note de frais dans custom_expense_reimbursement_indirect ?", mock_graph)
    assert res.is_resolved is True
    assert res.source_step == "exact_technical_mention"
    assert "custom.reimbursement.request" in res.resolved_models


def test_s2_0_unresolved_concept(mock_graph):
    res = resolve_business_term("Quelle est la météo à Paris aujourd'hui ?", mock_graph)
    assert res.is_resolved is False
    assert res.source_step == "unresolved"
    assert res.confidence == 0.0


# --- Bounded LLM Arbitration Tests ------------------------------------

class _FakeLLMResponse:
    def __init__(self, content):
        self.content = content


class _FakeLLM:
    def __init__(self, reply: str):
        self._reply = reply

    def invoke(self, messages):
        return _FakeLLMResponse(self._reply)


@pytest.fixture
def ambiguous_graph():
    """Two Field labels with near-identical fuzzy scores against the same
    query, mirroring the real 'purchase order approval' case.

    Section 1064: the deterministic tiebreak now only breaks a tie on a
    model-name segment that is RARE across the graph's own model population
    (same discipline as matching.py's rare-token evidence, Section 1040) --
    on the real 535-model graph 'order' alone names 10 models, so it cannot
    discriminate between two tied candidates that both plausibly fit. A
    2-model graph makes every segment trivially 'rare' (floor of 3 owners)
    and would let 'order' decide the tie by fixture accident rather than by
    genuine signal, defeating the point of this fixture -- a handful of
    unrelated '.order'-bearing models restores that realistic rarity so the
    scenario stays genuinely ambiguous and reaches LLM arbitration, exactly
    as the real production case does.
    """
    G = nx.DiGraph()
    G.add_node("model:custom.purchase.request", node_type="Model", name="custom.purchase.request")
    G.add_node("model:purchase.order.line", node_type="Model", name="purchase.order.line")
    G.add_node("field:f1", node_type="Field", label="purchase order approval request", model="custom.purchase.request")
    G.add_node("field:f2", node_type="Field", label="purchase order line approval", model="purchase.order.line")
    for extra in ("sale.order", "pos.order", "repair.order", "mrp.production.order"):
        G.add_node(f"model:{extra}", node_type="Model", name=extra)
    return G


def test_s2_0_llm_arbitration_picks_valid_candidate(ambiguous_graph):
    fake_llm = _FakeLLM(reply="custom.purchase.request")
    res = resolve_business_term("purchase order approval", ambiguous_graph, llm=fake_llm)
    assert res.source_step == "llm_arbitration"
    assert res.resolved_models == ["custom.purchase.request"]
    assert res.confidence == 0.6


def test_s2_0_llm_arbitration_rejects_out_of_list_hallucination(ambiguous_graph):
    fake_llm = _FakeLLM(reply="account.move")  # not in the closed candidate list
    res = resolve_business_term("purchase order approval", ambiguous_graph, llm=fake_llm)
    assert res.source_step == "unresolved"
    assert res.is_resolved is False


def test_s2_0_llm_arbitration_none_response_falls_back_unresolved(ambiguous_graph):
    fake_llm = _FakeLLM(reply="NONE")
    res = resolve_business_term("purchase order approval", ambiguous_graph, llm=fake_llm)
    assert res.source_step == "unresolved"


def test_s2_0_no_llm_call_when_top_candidate_is_clear(mock_graph):
    """Clear exact-mention resolution must never trigger LLM arbitration."""
    def _should_not_be_called(*args, **kwargs):
        raise AssertionError("LLM should not be invoked when resolution is unambiguous")

    fake_llm = type("Blocker", (), {"invoke": _should_not_be_called})()
    res = resolve_business_term("workflow de custom.purchase.request", mock_graph, llm=fake_llm)
    assert res.source_step == "exact_technical_mention"

def _graph_with_models(*models):
    graph = nx.DiGraph()
    for model in models:
        graph.add_node(f"model:{model}", node_type="Model", name=model)
    return graph


def test_exact_mention_ignores_business_phrase_without_alias():
    graph = _graph_with_models("sale.order", "purchase.order")

    result = resolve_business_term("quel est le workflow de sale.order pour une demande d'achat ?", graph)

    assert result.source_step == "exact_technical_mention"
    assert result.resolved_models == ["sale.order"]



def test_manual_alias_modules_are_gone():
    """Les tables d'alias manuels ont ete retirees (journal 1436-1438) : ne pas les reintroduire."""
    import importlib
    for name in (
        "code_intelligence.agent.aliases",
        "code_intelligence.agent.resolution.alias_lookup",
        "code_intelligence.agent.resolution.alias_targets",
    ):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(name)
