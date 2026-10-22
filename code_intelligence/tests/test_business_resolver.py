"""
code_intelligence/tests/test_business_resolver.py

J3 — Unit tests for business_resolver.resolve_business_term(), isolated from
the knowledge graph on disk. Uses a small synthetic graph fixture so these
tests run fast and don't depend on /home/user/odoo-17.0 being present.

Categories per plan J3: synonyms, ambiguous cases, out-of-scope cases.
Also covers J2's bounded LLM arbitration contract (closed candidate list,
never a default guess, low confidence tag).
"""
from types import SimpleNamespace
from unittest.mock import Mock

import networkx as nx
import pytest

from code_intelligence.agent.resolution.resolver import resolve_business_term, AMBIGUITY_GAP_THRESHOLD


@pytest.fixture
def sample_graph() -> nx.DiGraph:
    """
    Minimal synthetic graph covering:
      - a model matched only by fuzzy label, single clear candidate
        (custom.asset.loan via "matériel" -- accented to match the query,
        to isolate the fuzzy path)
      - three near-tied models to reproduce the "client vip" ambiguous case
      - a menu node reachable via OPENS_MODEL
    """
    G = nx.DiGraph()

    G.add_node("model:custom.asset.loan", node_type="Model",
               name="custom.asset.loan", description="Prêt de matériel")
    G.add_node("model:account.move", node_type="Model", name="account.move")
    G.add_node("model:custom.reimbursement.request", node_type="Model",
               name="custom.reimbursement.request")

    G.add_node("model:res.partner", node_type="Model",
               name="res.partner", description="Vip Client Contact")
    G.add_node("model:res.config.settings", node_type="Model",
               name="res.config.settings", description="Vip Client Configuration")
    G.add_node("model:auth.oauth.provider", node_type="Model",
               name="auth.oauth.provider", description="Vip Client OAuth Provider")

    G.add_node("model:hr.leave", node_type="Model", name="hr.leave", description="")
    G.add_node("menu:hr.menu_open_leave", node_type="Menu", name="Conges")
    G.add_edge("menu:hr.menu_open_leave", "model:hr.leave", edge_type="OPENS_MODEL")

    return G


def _mock_llm(content: str) -> Mock:
    """Build a minimal LangChain-shaped mock: llm.invoke(messages) -> obj.content"""
    m = Mock()
    m.invoke.return_value = SimpleNamespace(content=content)
    return m


# ---------------------------------------------------------------------------
# Synonyms — fuzzy path (single
# clear candidate -> no ambiguity, no LLM call)
# ---------------------------------------------------------------------------

def test_term_falls_back_to_fuzzy_graph_match(sample_graph):
    """
    "matériel" should resolve via fuzzy matching against the graph's Model.description labels.
    """
    result = resolve_business_term("matériel", sample_graph)
    assert result.is_resolved
    assert result.source_step == "fuzzy_graph_match"
    assert "custom.asset.loan" in result.resolved_models


def test_clear_top1_fuzzy_match_does_not_invoke_llm(sample_graph):
    """
    A single clear fuzzy candidate must resolve directly (source_step =
    fuzzy_graph_match) without ever calling the LLM, even if an llm client
    is passed in -- arbitration is reserved for genuine ambiguity.
    """
    mock_llm = Mock()
    result = resolve_business_term("matériel", sample_graph, llm=mock_llm)
    assert result.source_step == "fuzzy_graph_match"
    mock_llm.invoke.assert_not_called()


def test_menu_label_resolves_via_opens_model_edge(sample_graph):
    """Menu.name -> OPENS_MODEL -> Model is one of the three indexed label sources ."""
    result = resolve_business_term("conges", sample_graph)
    assert result.is_resolved
    assert "hr.leave" in result.resolved_models


# ---------------------------------------------------------------------------
# Ambiguous cases -- bounded LLM arbitration ()
# ---------------------------------------------------------------------------

def test_ambiguous_fuzzy_match_with_llm_picking_valid_candidate(sample_graph):
    """LLM arbitration selects a candidate from the closed list -> resolved, low confidence."""
    mock_llm = _mock_llm("res.partner")
    result = resolve_business_term("client vip", sample_graph, llm=mock_llm)
    assert result.is_resolved
    assert result.source_step == "llm_arbitration"
    assert result.resolved_models == ["res.partner"]
    assert result.confidence == 0.6, (
        "LLM-derived resolutions must be tagged with bounded/low confidence, "
        "never presented as a certain structural fact (per plan  spirit)."
    )
    mock_llm.invoke.assert_called_once()


def test_ambiguous_fuzzy_match_llm_says_none_is_unresolved(sample_graph):
    """LLM explicitly declines (NONE) -> unresolved, not a silent fallback to fuzzy top-1."""
    mock_llm = _mock_llm("NONE")
    result = resolve_business_term("client vip", sample_graph, llm=mock_llm)
    assert result.is_resolved is False
    assert result.source_step == "unresolved"


def test_ambiguous_fuzzy_match_llm_hallucinates_out_of_list_is_unresolved(sample_graph):
    """
    LLM returns a model name that is NOT in the closed candidate list
    (hallucination) -> must be rejected and treated as failed arbitration,
    never trusted, per the closed-list constraint in the system prompt.
    """
    mock_llm = _mock_llm("some.hallucinated.model")
    result = resolve_business_term("client vip", sample_graph, llm=mock_llm)
    assert result.is_resolved is False
    assert result.source_step == "unresolved"
    assert "some.hallucinated.model" not in result.resolved_models


def test_ambiguous_fuzzy_match_llm_call_failure_is_unresolved(sample_graph):
    """If the LLM call itself raises, arbitration must fail closed, not propagate the exception."""
    mock_llm = Mock()
    mock_llm.invoke.side_effect = RuntimeError("simulated API failure")
    result = resolve_business_term("client vip", sample_graph, llm=mock_llm)
    assert result.is_resolved is False
    assert result.source_step == "unresolved"


def test_ambiguity_gap_threshold_is_a_positive_number():
    """Sanity check on the tunable constant itself, so a future edit can't silently zero it out."""
    assert AMBIGUITY_GAP_THRESHOLD > 0


# ---------------------------------------------------------------------------
# Out-of-scope cases
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("query", [
    "quelle heure est-il ?",
    "raconte moi une blague",
    "what is the weather today",
    "xyzabc123 nonsense query",
])
def test_out_of_scope_query_is_unresolved(sample_graph, query):
    result = resolve_business_term(query, sample_graph)
    assert result.is_resolved is False
    assert result.source_step == "unresolved"
    assert result.confidence == 0.0


def test_empty_query_is_unresolved_without_graph_lookup():
    result = resolve_business_term("", None)
    assert result.is_resolved is False
    assert "empty" in result.reason.lower()


# ---------------------------------------------------------------------------
# Exact technical model-name mention (2026-08-06 fix): a question can name
# the technical model directly, bypassing the need for a good _description
# or a business alias. Found via a live E2E check on custom.deep.document,
# whose description ("Deep Inheritance Document Base") does not reliably
# fuzzy-match a question that instead names the model verbatim -- silently
# leaving is_resolved False and disabling every Bloc-9 forced dispatch.
# ---------------------------------------------------------------------------

def test_exact_technical_model_mention_resolves_even_with_unrelated_description(sample_graph):
    """custom.asset.loan's description is 'Prêt de matériel' (French, no
    lexical overlap with the dotted technical name) -- naming the technical
    identifier directly must still resolve, not depend on fuzzy-matching
    the description text."""
    result = resolve_business_term(
        "Dans le modèle custom.asset.loan, quelles sont les conditions ?",
        sample_graph,
    )
    assert result.is_resolved
    assert result.resolved_models == ["custom.asset.loan"]
    assert result.source_step == "exact_technical_mention"
    assert result.confidence == 1.0


def test_exact_technical_model_mention_in_a_sentence():
    """Une mention technique exacte dans une phrase resout le modele (Step 0)."""
    G = nx.DiGraph()
    G.add_node("model:account.move", node_type="Model", name="account.move", description="")
    result = resolve_business_term("un avoir concernant le modèle account.move", G)
    assert result.is_resolved
    assert result.resolved_models == ["account.move"]
    assert result.source_step == "exact_technical_mention"


def test_exact_technical_model_mention_does_not_match_substring_of_longer_identifier():
    r"""'custom.deep.document' must not spuriously match inside a longer,
    unrelated dotted identifier that merely contains it as a substring.

    Section 890 (todo/contexte.txt): this test's own name documented the
    intended behavior before the fix existed to actually deliver it -- the
    plain \w-boundary regex ('.' is not \w) could not tell a genuine mention
    apart from being merely the prefix of a longer dotted identifier (the
    bug that made 'base' match inside 'base.group_portal', SAL-Q1). The
    (?!\.\w) lookahead added for that fix closes this gap for the EXACT
    technical-mention step, but not for fuzzy matching: _fuzzy_match_graph
    also indexes a model's own technical name as a label for itself, and
    rapidfuzz's token-set scoring strips all punctuation before comparing,
    so it cannot see the dot-boundary distinction at all -- a genuinely
    separate code path with the same symptom. Section 1064 adds the
    matching guard there (_dotted_technical_name_only_embedded).
    """
    G = nx.DiGraph()
    G.add_node("model:custom.deep.document", node_type="Model",
               name="custom.deep.document",
               # Section 1064: deliberately shares no token with the query
               # below -- the original "Deep Inheritance Document Base"
               # happened to share "deep"/"document" with the query text,
               # which (once the technical-name self-match was correctly
               # guarded) let the DESCRIPTION's own, unrelated fuzzy match
               # resolve the model instead, masking whether the embedded-
               # substring bug this test targets was actually fixed.
               description="Internal archival hierarchy record")
    result = resolve_business_term(
        "un champ nommé other.custom.deep.document.extended existe-t-il ?", G,
    )
    assert not result.is_resolved


def test_exact_multi_model_mentions_are_all_preserved():
    G = nx.DiGraph()
    for model in ("stock.quant", "stock.move.line"):
        G.add_node(f"model:{model}", node_type="Model", name=model, description="")

    result = resolve_business_term(
        "Consulter stock.quant et modifier stock.move.line",
        G,
    )

    assert result.resolved_models == ["stock.move.line", "stock.quant"]
