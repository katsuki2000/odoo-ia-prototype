# -*- coding: utf-8 -*-
"""
tests/test_business_resolver_specificity.py

rank_by_specificity() orders several exact technical model mentions found
in the same query, using segment count / length / custom prefix / occurrence
count as tie-breakers, mirroring the arbitration idea already used on the
fuzzy-match path via AMBIGUITY_GAP_THRESHOLD. It used to also eliminate the
least specific mention; todo/contexte.txt section 1004 (STK-Q1: a real reply
dropped "stock.quant" because "stock.move.line" had more segments, even
though the question named both) removed that elimination -- an exact
mention is a co-target the dispatcher must not drop, not noise to filter
out. The ranking is now for dispatch order only; all mentions survive.

This file covers:
  1. _specificity_score / rank_by_specificity in isolation.
  2. The exact reported scenario end-to-end through resolve_business_term().
"""

from code_intelligence.agent.resolution.matching import rank_by_specificity, _specificity_score
from code_intelligence.agent.resolution.resolver import resolve_business_term


class _FakeGraph:
    """Minimal stand-in for the networkx knowledge graph: only the methods
    actually used by _find_exact_technical_model_mentions / _build_fuzzy_index
    are implemented."""

    def __init__(self, model_names):
        self._nodes = [
            (f"model:{name}", {"node_type": "Model", "name": name})
            for name in model_names
        ]
        self.edges = {}

    def nodes(self, data=False):
        if data:
            return self._nodes
        return [n for n, _d in self._nodes]

    def number_of_nodes(self):
        return len(self._nodes)

    def successors(self, node_id):
        return []


# ---------------------------------------------------------------------------
# 1. rank_by_specificity / _specificity_score in isolation
# ---------------------------------------------------------------------------

class TestRankBySpecificity:
    def test_noop_with_a_single_match(self):
        assert rank_by_specificity(["base"], "peut-on voir base ?") == ["base"]

    def test_noop_with_empty_list(self):
        assert rank_by_specificity([], "peu importe") == []

    def test_more_segments_ranks_first_but_both_survive(self):
        """'base' (1 segment) vs 'custom.deep.document' (3 segments)
        mentioned in the same query: the specific one ranks first, but
        (section 1004) an exact mention is never dropped -- both models
        were named literally and both must reach dispatch."""
        matches = ["base", "custom.deep.document"]
        query = "un utilisateur peut-il voir custom.deep.document ou base ?"
        result = rank_by_specificity(matches, query)
        assert result[0] == "custom.deep.document"
        assert set(result) == {"base", "custom.deep.document"}

    def test_order_of_input_list_does_not_matter(self):
        matches = ["custom.deep.document", "base"]
        query = "un utilisateur peut-il voir custom.deep.document ou base ?"
        assert rank_by_specificity(matches, query)[0] == "custom.deep.document"

    def test_true_tie_keeps_both_candidates(self):
        """Two equally-specific technical names (same segment count, same
        length, same prefix status, same occurrence count) must both be
        kept -- rank_by_specificity never picks an arbitrary winner between
        genuinely tied candidates."""
        matches = ["custom.aaaa", "custom.bbbb"]
        query = "difference entre custom.aaaa et custom.bbbb"
        result = rank_by_specificity(matches, query)
        assert set(result) == {"custom.aaaa", "custom.bbbb"}

    def test_custom_prefix_breaks_a_segment_and_length_tie(self):
        """Same segment count (2) and same length (8 chars) -- differ only
        by the custom/business prefix ('x_' vs no prefix): prefix wins the
        ranking order (both mentions still reach dispatch, section 1004)."""
        matches = ["ir.model", "x_.model"]
        query = "difference entre ir.model et x_.model"
        result = rank_by_specificity(matches, query)
        assert result[0] == "x_.model"
        assert set(result) == {"ir.model", "x_.model"}

    def test_more_occurrences_breaks_a_remaining_tie(self):
        """Same segments/length/prefix -- only occurrence count in the
        query differs."""
        matches = ["custom.report", "custom.record"]
        query = "custom.report custom.report contre custom.record"
        result = rank_by_specificity(matches, query)
        assert result[0] == "custom.report"
        assert set(result) == {"custom.report", "custom.record"}


class TestSpecificityScore:
    def test_segments_length_prefix_occurrences_tuple(self):
        is_explicit, has_context, is_domain, segments, length, is_custom, occurrences = _specificity_score(
            "custom.deep.document", "voir custom.deep.document"
        )
        assert segments == 3
        assert length == len("custom.deep.document")
        assert is_custom == 1
        assert occurrences == 1

    def test_generic_short_name_scores_strictly_lower_than_specific_one(self):
        base_score = _specificity_score("base", "voir base et custom.deep.document")
        deep_score = _specificity_score(
            "custom.deep.document", "voir base et custom.deep.document"
        )
        assert deep_score > base_score


# ---------------------------------------------------------------------------
# 2. End-to-end through resolve_business_term() -- the exact reported bug
# ---------------------------------------------------------------------------

class TestResolveBusinessTermExactMentionArbitration:
    def test_generic_and_specific_exact_mentions_both_reach_dispatch(self):
        """Both models are named literally: resolve_business_term must not
        drop either (section 1004) -- the specific one ranks first."""
        G = _FakeGraph(["base", "custom.deep.document"])
        question = "Quel est le lien entre le modèle base et le modèle custom.deep.document ?"

        concept = resolve_business_term(question, G, llm=None)

        assert concept.is_resolved is True
        assert concept.source_step == "exact_technical_mention"
        assert concept.resolved_models[0] == "custom.deep.document"
        assert set(concept.resolved_models) == {"base", "custom.deep.document"}

    def test_single_exact_mention_is_unaffected(self):
        """No arbitration needed/triggered when only one exact technical
        name is mentioned -- unchanged from before this fix."""
        G = _FakeGraph(["custom.purchase.request"])
        question = "Que fait custom.purchase.request ?"

        concept = resolve_business_term(question, G, llm=None)

        assert concept.resolved_models == ["custom.purchase.request"]

    def test_two_genuinely_tied_specific_names_are_both_kept(self):
        """Arbitration must not silently drop a legitimate second model
        just because two exact mentions happen to be equally specific."""
        G = _FakeGraph(["custom.module.aaaa", "custom.module.bbbb"])
        question = "Quelle difference entre custom.module.aaaa et custom.module.bbbb ?"

        concept = resolve_business_term(question, G, llm=None)

        assert set(concept.resolved_models) == {
            "custom.module.aaaa", "custom.module.bbbb",
        }
