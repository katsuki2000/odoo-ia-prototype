"""The source footer states what an answer rests on: the graph label requires at least one supporting observation."""

import time
from unittest import mock

import pytest

from code_intelligence.agent.context import DispatchContext
from code_intelligence.agent.matching import ResolvedConcept
from code_intelligence.agent.postprocess import build_final_response
from code_intelligence.agent.provenance import (
    GRAPH_SOURCE_FOOTER,
    UNSUPPORTED_SOURCE_FOOTER,
    source_footer,
)
from core.evidence.evidence_sufficiency import EvidenceSufficiencyResult, EvidenceSufficiencyStatus
from core.verification.extractors import SOURCE_FOOTER_RE

SUFFICIENT = EvidenceSufficiencyStatus.SUFFICIENT
INSUFFICIENT = EvidenceSufficiencyStatus.INSUFFICIENT


def _result(status, relevant=0, total=0, failure=False):
    return EvidenceSufficiencyResult(
        status=status,
        relevant_observation_count=relevant,
        total_observation_count=total,
        has_execution_failure=failure,
    )


@pytest.mark.parametrize(
    "sufficiency, expected",
    [
        (_result(SUFFICIENT, relevant=2, total=2), GRAPH_SOURCE_FOOTER),
        (_result(INSUFFICIENT, relevant=0, total=0), UNSUPPORTED_SOURCE_FOOTER),
        (_result(INSUFFICIENT, relevant=0, total=10), UNSUPPORTED_SOURCE_FOOTER),
        (_result(INSUFFICIENT, relevant=1, total=3), GRAPH_SOURCE_FOOTER),
        (_result(INSUFFICIENT, relevant=0, total=2, failure=True), GRAPH_SOURCE_FOOTER),
    ],
)
def test_source_footer_follows_the_evidence(sufficiency, expected):
    assert source_footer(sufficiency) == expected


@pytest.mark.parametrize("footer", [GRAPH_SOURCE_FOOTER, UNSUPPORTED_SOURCE_FOOTER])
def test_footer_is_one_line_the_verifier_strips_entirely(footer):
    assert "\n" not in footer
    assert SOURCE_FOOTER_RE.fullmatch(footer)


def _context(observations=(), models=(), tools=(), resolved=()):
    concept = ResolvedConcept(
        user_term="",
        resolved_models=list(resolved),
        resolved_modules=[],
        confidence=1.0 if resolved else 0.0,
        source_step="static_alias" if resolved else "unresolved",
        is_resolved=bool(resolved),
        reason="",
    )
    ctx = DispatchContext(
        G=None, concept=concept, question="comment gerer les bons de commande ?", tool_map={},
        resolved_user_group_xmlids=None, trace_logger=mock.MagicMock(), trace_id="t", hop_cap=15,
    )
    ctx.tool_observations = list(observations)
    ctx.tool_observation_models = list(models)
    ctx.tool_observation_tools = list(tools)
    ctx.hop_count = len(ctx.tool_observations)
    return ctx


def _final_answer_last_line(ctx):
    out = build_final_response(ctx, "Reponse du modele.", {}, time.perf_counter(), 0.0, None)
    return out["response"].answer.strip().splitlines()[-1]


def test_answer_without_any_observation_is_labelled_as_general_knowledge():
    assert _final_answer_last_line(_context()) == UNSUPPORTED_SOURCE_FOOTER


def test_answer_with_a_supporting_observation_keeps_the_graph_label():
    ctx = _context(
        observations=["Pour 'account.move': menu Invoicing -> Customers -> Invoices (id: account.menu_action_move_out_invoice_type)."],
        models=["account.move"],
        tools=["describe_navigation_path"],
        resolved=["account.move"],
    )
    assert _final_answer_last_line(ctx) == GRAPH_SOURCE_FOOTER
