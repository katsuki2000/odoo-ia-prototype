# -*- coding: utf-8 -*-
"""
tests/test_business_resolver_specificity.py

Option 2 fix (todo/contexte.txt section 2xx): several exact technical model
mentions can coexist in the same query -- a generic name like "base"
alongside a specific one like "custom.deep.document" -- with nothing
previously choosing the more relevant one. The naive fix (blacklisting
"base") is ad hoc and would need to be re-applied for every future generic
technical name ("mail", "stock", "account", ...). rank_by_specificity()
arbitrates deterministically instead, using segment count / length / custom
prefix / occurrence count as tie-breakers, mirroring the arbitration idea
already used on the fuzzy-match path via AMBIGUITY_GAP_THRESHOLD.

This file covers:
  1. _specificity_score / rank_by_specificity in isolation.
  2. The exact reported scenario end-to-end through resolve_business_term().
"""
import pytest

from code_intelligence.agent.matching import rank_by_specificity, _specificity_score
from code_intelligence.agent.resolver import resolve_business_term


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

    def test_more_segments_wins_over_generic_short_name(self):
        """The exact reported bug: 'base' (1 segment) vs
        'custom.deep.document' (3 segments) mentioned in the same query --
        only the specific one should survive arbitration."""
        matches = ["base", "custom.deep.document"]
        query = "un utilisateur peut-il voir custom.deep.document ou base ?"
        assert rank_by_specificity(matches, query) == ["custom.deep.document"]

    def test_order_of_input_list_does_not_matter(self):
        matches = ["custom.deep.document", "base"]
        query = "un utilisateur peut-il voir custom.deep.document ou base ?"
        assert rank_by_specificity(matches, query) == ["custom.deep.document"]

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
        by the custom/business prefix ('x_' vs no prefix): prefix wins."""
        matches = ["ir.model", "x_.model"]
        query = "difference entre ir.model et x_.model"
        result = rank_by_specificity(matches, query)
        assert result == ["x_.model"]

    def test_more_occurrences_breaks_a_remaining_tie(self):
        """Same segments/length/prefix -- only occurrence count in the
        query differs."""
        matches = ["custom.report", "custom.record"]
        query = "custom.report custom.report contre custom.record"
        result = rank_by_specificity(matches, query)
        assert result == ["custom.report"]


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
    def test_generic_and_specific_exact_mentions_resolve_to_specific_only(self):
        G = _FakeGraph(["base", "custom.deep.document"])
        question = "Quel est le lien entre base et custom.deep.document ?"

        concept = resolve_business_term(question, G, llm=None)

        assert concept.is_resolved is True
        assert concept.source_step == "exact_technical_mention"
        assert concept.resolved_models == ["custom.deep.document"]
        assert "base" not in concept.resolved_models

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
