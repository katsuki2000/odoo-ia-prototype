"""
code_intelligence/tests/test_ci_agent_tools_resolution.py

J3 — Structural guard test: composite/auxiliary tools must resolve a
business-term model_name (e.g. "avoir") to its technical Odoo model
(e.g. "account.move") before calling their underlying _impl, even when
the upstream LLM did not follow the system-prompt hint.
"""
import networkx as nx
import pytest

from code_intelligence import ci_agent_tools


@pytest.fixture
def sample_graph_with_alias_target() -> nx.DiGraph:
    G = nx.DiGraph()
    G.add_node("model:account.move", node_type="Model", name="account.move", description="Journal Entry")
    G.add_node("model:custom.asset.loan", node_type="Model", name="custom.asset.loan", description="Prêt de matériel")
    return G


def test_resolve_model_param_passes_through_valid_technical_name(sample_graph_with_alias_target):
    ci_agent_tools.set_graph_ref(sample_graph_with_alias_target)
    assert ci_agent_tools._resolve_model_param("account.move") == "account.move"


def test_resolve_model_param_resolves_business_term_via_static_alias(sample_graph_with_alias_target):
    ci_agent_tools.set_graph_ref(sample_graph_with_alias_target)
    assert ci_agent_tools._resolve_model_param("avoir") == "account.move"


def test_resolve_model_param_resolves_business_term_via_fuzzy(sample_graph_with_alias_target):
    ci_agent_tools.set_graph_ref(sample_graph_with_alias_target)
    assert ci_agent_tools._resolve_model_param("matériel") == "custom.asset.loan"


def test_resolve_model_param_leaves_unresolvable_term_unchanged(sample_graph_with_alias_target):
    """
    Nonsense input must pass through unchanged rather than being guessed --
    the downstream tool's own "model not found" check then surfaces the
    error to the LLM.
    """
    ci_agent_tools.set_graph_ref(sample_graph_with_alias_target)
    result = ci_agent_tools._resolve_model_param("xyzabc123nonsense")
    assert result == "xyzabc123nonsense"


def test_qui_a_acces_a_resolves_business_term_end_to_end(sample_graph_with_alias_target, monkeypatch):
    """
    End-to-end guard: calling the qui_a_acces_a tool with a raw business
    term ("avoir") instead of the technical model name must still work,
    because _resolve_model_param() runs before _impl() is invoked.
    """
    ci_agent_tools.set_graph_ref(sample_graph_with_alias_target)

    captured = {}

    class _FakeResult:
        summary_text = "OK"

    def _fake_impl(G, model_name, droit="read", group_id=None):
        captured["model_name"] = model_name
        return _FakeResult()

    monkeypatch.setattr(
        "code_intelligence.deterministic_tools.qui_a_acces_a", _fake_impl
    )

    ci_agent_tools.qui_a_acces_a.invoke({"model_name": "avoir", "droit": "read"})
    assert captured["model_name"] == "account.move", (
        "The tool must call the underlying implementation with the resolved "
        "technical model name, not the raw business term the LLM supplied."
    )
