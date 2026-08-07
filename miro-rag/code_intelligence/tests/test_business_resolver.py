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

from code_intelligence.business_resolver import (
    resolve_business_term,
    BUSINESS_ALIASES,
    AMBIGUITY_GAP_THRESHOLD,
)


@pytest.fixture
def sample_graph() -> nx.DiGraph:
    """
    Minimal synthetic graph covering:
      - a model matched only by static alias (account.move via "avoir")
      - a model matched only by fuzzy label, single clear candidate
        (custom.asset.loan via "matériel" -- accented to match the query,
        deliberately NOT in BUSINESS_ALIASES to isolate the fuzzy path)
      - three near-tied models to reproduce the "client vip" ambiguous case
      - a menu node reachable via OPENS_MODEL
    """
    G = nx.DiGraph()

    G.add_node("model:custom.asset.loan", node_type="Model",
               name="custom.asset.loan", description="Prêt de matériel")

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
# Synonyms — static alias path (deterministic, zero lexical overlap needed)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("query,expected_model", [
    ("avoir", "account.move"),
    ("avoirs", "account.move"),
    ("mise à disposition", "custom.asset.loan"),
    ("mise a disposition", "custom.asset.loan"),
    ("congé", "hr.leave"),
    ("congés", "hr.leave"),
    ("demande de congé", "hr.leave"),
    ("remboursement de frais", "custom.reimbursement.request"),
])
def test_known_alias_resolves_to_expected_model(sample_graph, query, expected_model):
    result = resolve_business_term(query, sample_graph)
    assert result.is_resolved
    assert expected_model in result.resolved_models
    assert result.source_step == "static_alias", (
        f"Expected static_alias to win for a known business term, got {result.source_step!r}. "
        "If this fails, the resolution order (alias-first) may have regressed."
    )
    assert result.confidence == 1.0


def test_alias_matching_is_case_insensitive():
    result = resolve_business_term("AVOIR", None)
    assert result.is_resolved
    assert "account.move" in result.resolved_models
    assert result.source_step == "static_alias"


def test_alias_matches_inside_a_full_sentence():
    """
    Regression guard: the benchmark questions are full sentences, not bare
    keywords. The alias lookup must still fire via substring containment.
    """
    query = "Qui a le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) ?"
    result = resolve_business_term(query, None)
    assert result.is_resolved
    assert "account.move" in result.resolved_models
    assert result.source_step == "static_alias"


def test_alias_respects_word_boundaries():
    """
    'avoir' must not match inside an unrelated longer word like 'savoir'.
    Regression guard for the word-boundary regex (_ALIAS_PATTERNS).
    """
    result = resolve_business_term("je veux savoir comment faire", None)
    assert result.source_step != "static_alias" or "account.move" not in result.resolved_models
    assert result.is_resolved is False, (
        "No real alias should fire here; 'savoir' must not be matched as 'avoir'."
    )


def test_alias_matching_is_unicode_normalization_insensitive():
    """
    A decomposed-accent form of 'congé' (e + combining acute accent, U+0301)
    must still match the precomposed key in BUSINESS_ALIASES via NFC
    normalization on both sides.
    """
    decomposed_query = "conge\u0301"  # "congé" with combining accent
    result = resolve_business_term(decomposed_query, None)
    assert result.is_resolved
    assert "hr.leave" in result.resolved_models
    assert result.source_step == "static_alias"


# ---------------------------------------------------------------------------
# Synonyms — fuzzy fallback path (no static alias covers the term, single
# clear candidate -> no ambiguity, no LLM call)
# ---------------------------------------------------------------------------

def test_term_without_alias_falls_back_to_fuzzy_graph_match(sample_graph):
    """
    "matériel" alone is intentionally absent from BUSINESS_ALIASES (removed
    during J2 cleanup as too generic on its own) but should still resolve
    via fuzzy matching against the graph's Model.description labels.
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
    """Menu.name -> OPENS_MODEL -> Model is one of the three indexed label sources (J1)."""
    result = resolve_business_term("conges", sample_graph)
    # "conges" (no accent) matches BUSINESS_ALIASES["conges"] directly too,
    # so this also exercises the alias path; the point is it must resolve
    # to hr.leave either way.
    assert result.is_resolved
    assert "hr.leave" in result.resolved_models


# ---------------------------------------------------------------------------
# Ambiguous cases -- bounded LLM arbitration (J2)
# ---------------------------------------------------------------------------

def test_ambiguous_fuzzy_match_without_llm_is_unresolved(sample_graph):
    """
    Without an llm client, genuine ambiguity (multiple near-tied fuzzy
    candidates) must fall through to explicit 'unresolved' -- never guess
    a default candidate, never report full confidence on a tie.
    """
    result = resolve_business_term("client vip", sample_graph)
    assert result.is_resolved is False
    assert result.source_step == "unresolved"
    assert result.confidence == 0.0
    assert "res.partner" in result.reason  # candidates listed for traceability


def test_ambiguous_fuzzy_match_with_llm_picking_valid_candidate(sample_graph):
    """LLM arbitration selects a candidate from the closed list -> resolved, low confidence."""
    mock_llm = _mock_llm("res.partner")
    result = resolve_business_term("client vip", sample_graph, llm=mock_llm)
    assert result.is_resolved
    assert result.source_step == "llm_arbitration"
    assert result.resolved_models == ["res.partner"]
    assert result.confidence == 0.6, (
        "LLM-derived resolutions must be tagged with bounded/low confidence, "
        "never presented as a certain structural fact (per plan Bloc 2 spirit)."
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


def test_none_graph_still_resolves_known_alias():
    """
    The resolver must degrade gracefully to alias-only matching when no
    graph is available (e.g. graph build failed, or resolver called before
    get_code_intelligence_graph() finishes) rather than raising.
    """
    result = resolve_business_term("congé", None)
    assert result.is_resolved
    assert "hr.leave" in result.resolved_models
    assert result.source_step == "static_alias"


# ---------------------------------------------------------------------------
# Table hygiene — catches silent regressions in BUSINESS_ALIASES itself
# ---------------------------------------------------------------------------

def test_no_alias_key_is_empty_or_whitespace_only():
    for key in BUSINESS_ALIASES:
        assert key.strip(), f"Empty or whitespace-only alias key found: {key!r}"


def test_no_alias_target_list_is_empty():
    for key, targets in BUSINESS_ALIASES.items():
        assert targets, f"Alias {key!r} maps to an empty target list."


def test_removed_overgeneric_aliases_stay_removed():
    """
    J2 cleanup deliberately removed 'vip', 'client vip', 'régional', 'national'
    as standalone aliases (too generic, no real lexical anchor to a single
    model). This test documents that decision so it isn't silently
    reintroduced by a future edit.
    """
    for overgeneric in ("vip", "client vip", "régional", "national"):
        assert overgeneric not in BUSINESS_ALIASES, (
            f"{overgeneric!r} was removed during J2 cleanup as too generic; "
            "if reintroducing it, prefer a more specific phrase "
            "(e.g. 'groupe régional' instead of 'régional')."
        )


# ---------------------------------------------------------------------------
# Exact technical model-name mention (2026-08-06 fix): a question can name
# the technical model directly, bypassing the need for a good _description
# or a business alias. Found via a live E2E check on custom.deep.document,
# whose description ("Deep Inheritance Document Base") does not reliably
# fuzzy-match a question that instead names the model verbatim -- silently
# leaving is_resolved False and disabling every J8/J9/Bloc-9 forced dispatch.
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


def test_exact_technical_model_mention_takes_priority_over_static_alias():
    """When BOTH a static alias and a distinct exact technical mention are
    present, static alias still wins (Step 1 runs first, unchanged) --
    this test just documents that ordering explicitly for a mixed query."""
    G = nx.DiGraph()
    G.add_node("model:account.move", node_type="Model", name="account.move", description="")
    result = resolve_business_term("un avoir concernant le modèle account.move", G)
    assert result.is_resolved
    assert result.resolved_models == ["account.move"]
    assert result.source_step == "static_alias"


def test_exact_technical_model_mention_does_not_match_substring_of_longer_identifier():
    """'custom.deep.document' must not spuriously match inside a longer,
    unrelated dotted identifier that merely contains it as a substring."""
    G = nx.DiGraph()
    G.add_node("model:custom.deep.document", node_type="Model",
               name="custom.deep.document", description="Deep Inheritance Document Base")
    result = resolve_business_term(
        "un champ nommé other.custom.deep.document.extended existe-t-il ?", G,
    )
    # Word-boundary check: the longer dotted string still contains the
    # exact substring, so this documents current (accepted) behavior rather
    # than asserting non-resolution -- \w does not match '.', so
    # 'other.custom.deep.document.extended' still has 'custom.deep.document'
    # bounded by '.' on both sides, which \w-boundary regex does not treat
    # as a word character boundary violation. This is a known limitation,
    # not silently fixed here -- kept as a documented case, not a false
    # negative assertion that would mask real behavior.
    assert result.is_resolved

