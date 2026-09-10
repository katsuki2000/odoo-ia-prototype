# -*- coding: utf-8 -*-
"""
tests/test_can_view_amount_fact_block_model_disambiguation.py

Defensive hardening (todo/contexte.txt section 2xx), companion to the
option 2 resolver fix (test_business_resolver_specificity.py): even after
the resolver stops returning spurious extra models, a genuinely
multi-model resolution can still make raw_tool_output carry more than one
[FAIT DETERMINISTIQUE] can_view_amount_v2 block -- one per resolved model,
since _format_can_view_amount_fact() never embeds the model name in the
block text itself. _extract_can_view_amount_fact_block() previously took
the FIRST block found by _has_can_view_amount_fact(), which is
order-dependent and can silently backfill the wrong model's verdict.

This file locks:
  1. The legacy (no model info) fallback behaviour is unchanged, including
     the fact that it stays order-dependent -- explicitly reproducing why
     the disambiguation parameters exist.
  2. With tool_observation_models/target_models supplied, the block
     actually belonging to the resolved model is picked instead.
  3. A genuine multi-model resolution (several distinct candidate models)
     falls back to the most recently computed block, deterministically.
  4. _backfill_missing_can_view_amount_fact forwards these parameters
     end-to-end and backfills the correct model's verdict.
"""
import pytest

from code_intelligence.agent.ci_agent_node.guards.can_view_verifier import (
    _extract_can_view_amount_fact_block,
    _backfill_missing_can_view_amount_fact,
    _format_can_view_amount_fact,
    _has_can_view_amount_fact,
)

# Two distinct models, two distinct verdicts for the same amount -- if the
# wrong block is picked, the returned answer would be silently inverted.
_BLOCK_BASE = _format_can_view_amount_fact(80000, True)
_BLOCK_DEEP = _format_can_view_amount_fact(80000, False)

_TOOL_OBSERVATIONS = [
    "Observation ACL pour le modele base.",
    _BLOCK_BASE,
    "Observation ACL pour le modele custom.deep.document.",
    _BLOCK_DEEP,
]
_TOOL_OBSERVATION_MODELS = ["base", "base", "custom.deep.document", "custom.deep.document"]
_RAW_TOOL_OUTPUT = "\n\n".join(_TOOL_OBSERVATIONS)


class TestExtractCanViewAmountFactBlockLegacyFallback:
    def test_no_model_info_returns_first_block_found_order_dependent(self):
        """Without tool_observation_models/target_models, behaviour is
        unchanged from before this fix -- including still being
        order-dependent when several blocks are present. This is the exact
        symptom the new parameters exist to fix (see the class below)."""
        block = _extract_can_view_amount_fact_block(_RAW_TOOL_OUTPUT)
        assert block == _BLOCK_BASE.strip()

    def test_single_block_is_unaffected(self):
        block = _extract_can_view_amount_fact_block(_BLOCK_DEEP)
        assert block == _BLOCK_DEEP.strip()

    def test_no_block_present_returns_none(self):
        assert _extract_can_view_amount_fact_block("Rien a signaler ici.") is None


class TestExtractCanViewAmountFactBlockModelAware:
    def test_picks_the_block_belonging_to_the_target_model(self):
        block = _extract_can_view_amount_fact_block(
            _RAW_TOOL_OUTPUT,
            tool_observation_models=_TOOL_OBSERVATION_MODELS,
            target_models=["custom.deep.document"],
        )
        assert block == _BLOCK_DEEP.strip()
        assert block != _BLOCK_BASE.strip()

    def test_picks_the_other_model_block_when_that_is_the_target(self):
        block = _extract_can_view_amount_fact_block(
            _RAW_TOOL_OUTPUT,
            tool_observation_models=_TOOL_OBSERVATION_MODELS,
            target_models=["base"],
        )
        assert block == _BLOCK_BASE.strip()

    def test_multiple_distinct_target_models_uses_most_recently_computed(self):
        """Genuine multi-model resolution: both models produced a fact
        block. Not a full per-model backfill yet, but deterministic instead
        of an arbitrary first match -- the last evaluation performed wins."""
        block = _extract_can_view_amount_fact_block(
            _RAW_TOOL_OUTPUT,
            tool_observation_models=_TOOL_OBSERVATION_MODELS,
            target_models=["base", "custom.deep.document"],
        )
        assert block == _BLOCK_DEEP.strip()

    def test_target_model_with_no_matching_block_falls_back_to_untargeted_scan(self):
        block = _extract_can_view_amount_fact_block(
            _RAW_TOOL_OUTPUT,
            tool_observation_models=_TOOL_OBSERVATION_MODELS,
            target_models=["some.other.model"],
        )
        assert block == _BLOCK_BASE.strip()


class TestBackfillForwardsModelDisambiguation:
    def test_backfills_the_correct_model_verdict_in_a_multi_model_scenario(self):
        final_answer = "Reponse synthetisee sans le fait can_view_amount_v2."

        result = _backfill_missing_can_view_amount_fact(
            final_answer,
            _RAW_TOOL_OUTPUT,
            tool_observation_models=_TOOL_OBSERVATION_MODELS,
            target_models=["custom.deep.document"],
        )

        assert _BLOCK_DEEP in result
        assert _BLOCK_BASE not in result
        assert _has_can_view_amount_fact(result) is True

    def test_legacy_two_arg_call_is_still_supported(self):
        """Backward compatibility: existing callers (and
        test_bloc9_02_backfill_can_view_amount_wiring.py) that never pass
        the new keyword arguments keep working unchanged."""
        final_answer = "Reponse sans le fait."
        result = _backfill_missing_can_view_amount_fact(final_answer, _BLOCK_DEEP)
        assert _BLOCK_DEEP in result
