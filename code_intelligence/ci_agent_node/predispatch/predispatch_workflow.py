"""
code_intelligence/ci_agent_node/predispatch_workflow.py

Deterministic pre-dispatch of 'describe_workflow' for workflow-related
questions. Extracted from the former ci_agent_node.py monolith (refactor,
see todo/contexte.txt). Behavior unchanged.
"""

import logging
import time

from code_intelligence.ci_agent_node.context.prompt_and_heuristics import (
    _truncate_observation,
    _tool_call_key,
)
from code_intelligence.ci_agent_node.context.context_extractors import _question_is_workflow_related
from code_intelligence.ci_agent_node.context.dispatch_context import DispatchContext

logger = logging.getLogger(__name__)


def dispatch_describe_workflow(ctx: DispatchContext) -> None:
    if not (
        ctx.concept.is_resolved and ctx.concept.resolved_models
        and _question_is_workflow_related(ctx.question)
        and not ctx.hop_budget_exhausted
    ):
        return

    wf_tool = ctx.tool_map.get("describe_workflow")
    if wf_tool is None:
        return

    for target_model in ctx.concept.resolved_models:
        call_key = _tool_call_key("describe_workflow", {"model_name": target_model})
        if call_key in ctx.seen_calls:
            continue
        t0 = time.perf_counter()
        try:
            observation = str(wf_tool.invoke({"model_name": target_model}))
            observation = _truncate_observation(observation, 3000)
            ctx.record_observation(
                "describe_workflow", {"model_name": target_model},
                observation, target_model, call_key, time.perf_counter() - t0,
            )
            logger.info(
                "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                "'describe_workflow' for model '%s'.",
                target_model,
            )
            if ctx.hop_budget_exhausted:
                break
        except Exception as te:
            logger.error("Deterministic describe_workflow dispatch failed: %s", te)

    if any(k and k[0] == "describe_workflow" for k in ctx.seen_calls):
        ctx.system_prompt_suffix += (
            "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
            "describe_workflow has already been run for the target model(s) above; "
            "its workflow state and transition structure is already included in the tool "
            "observations. Do not call describe_workflow again."
        )
