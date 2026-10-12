"""
code_intelligence/tests/test_ci_agent_tools_resolution.py

J3 — Structural guard test: composite/auxiliary tools must resolve a
business-term model_name (e.g. "avoir") to its technical Odoo model
(e.g. "account.move") before calling their underlying _impl, even when
the upstream LLM did not follow the system-prompt hint.
"""
import networkx as nx
import pytest

from code_intelligence.agent import tool_helpers as ci_agent_tools
from code_intelligence.agent import tools as _ci_tools
ci_agent_tools.who_has_access_to = _ci_tools.who_has_access_to


@pytest.fixture
def sample_graph_with_alias_target() -> nx.DiGraph:
    G = nx.DiGraph()
    G.add_node("model:account.move", node_type="Model", name="account.move", description="Journal Entry")
    G.add_node("model:custom.asset.loan", node_type="Model", name="custom.asset.loan", description="Prêt de matériel")
    return G


def test_resolve_model_param_passes_through_valid_technical_name(sample_graph_with_alias_target):
    ci_agent_tools.set_graph_ref(sample_graph_with_alias_target)
    assert ci_agent_tools._resolve_model_param("account.move") == "account.move"


def test_resolve_model_param_returns_term_unchanged_when_alias_disabled(sample_graph_with_alias_target):
    # Option A (section 1273): static aliases are off in production.
    # "avoir" does not resolve without a dense backend in test context;
    # _resolve_model_param returns the term unchanged so the downstream
    # tool surfaces a "model not found" message to the LLM.
    ci_agent_tools.set_graph_ref(sample_graph_with_alias_target)
    assert ci_agent_tools._resolve_model_param("avoir") == "avoir"


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


def test_qui_a_acces_a_passes_exact_technical_name_through(sample_graph_with_alias_target, monkeypatch):
    """
    J3 structural guard: _resolve_model_param() runs before _impl().
    Option A (section 1273): static aliases are off in production.
    When the LLM passes a technical name that exists in the graph, it
    passes through unchanged. When it passes an unresolvable business
    term, the tool receives it unchanged and surfaces a model-not-found
    message -- the LLM can then retry with a candidate name.
    """
    ci_agent_tools.set_graph_ref(sample_graph_with_alias_target)

    captured = {}

    class _FakeResult:
        summary_text = "OK"
        evidence = []

    def _fake_impl(G, model_name, permission="read", group_id=None):
        captured["model_name"] = model_name
        return _FakeResult()

    monkeypatch.setattr(
        "code_intelligence.rules.access_evaluator.who_has_access_to", _fake_impl
    )

    ci_agent_tools.who_has_access_to.invoke({"model_name": "account.move", "permission": "read"})
    assert captured["model_name"] == "account.move", (
        "_resolve_model_param must pass a valid technical name through unchanged."
    )
