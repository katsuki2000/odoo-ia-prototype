"""
code_intelligence/ci_agent_node/predispatch_security_locks.py

Deterministic pre-dispatch of 'analyze_security_locks' when the resolved
concept targets model(s) and the question isn't inheritance-related.
Extracted from the former ci_agent_node.py monolith (refactor, see
todo/contexte.txt). Behavior unchanged.
"""

import logging
import time

from code_intelligence.knowledge_rules.security.gate import gate_observation
from code_intelligence.agent.ci_agent_node.context.prompt_and_heuristics import (
    _truncate_observation,
    _tool_call_key,
)
from code_intelligence.agent.ci_agent_node.context.context_extractors import _question_is_inheritance_related
from code_intelligence.agent.ci_agent_node.context.dispatch_context import DispatchContext

logger = logging.getLogger(__name__)


def dispatch_security_locks(ctx: DispatchContext) -> None:
    if not (
        ctx.concept.is_resolved and ctx.concept.resolved_models
        and not ctx.hop_budget_exhausted
        and not _question_is_inheritance_related(ctx.question)
    ):
        return

    from .forced_dispatch_predicates import security_locks_targets

    lock_tool = ctx.tool_map.get("analyze_security_locks")
    if lock_tool is None:
        return

    for target_model in security_locks_targets(ctx.concept, ctx.G)[:1]:
        call_key = _tool_call_key("analyze_security_locks", {"model_name": target_model})
        if call_key in ctx.seen_calls:
            continue
        t0 = time.perf_counter()
        try:
            observation = str(lock_tool.invoke({"model_name": target_model}))
            observation = _truncate_observation(observation, 3000)
            observation, omitted_list = gate_observation(
                tool_name="analyze_security_locks",
                model_name=target_model,
                observation=observation,
                G=ctx.G,
                user_groups=ctx.resolved_user_group_xmlids,
            )
            ctx.omitted_items.extend(omitted_list)
            ctx.record_observation(
                "analyze_security_locks", {"model_name": target_model},
                observation, target_model, call_key, time.perf_counter() - t0,
            )
            logger.info(
                "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                "'analyze_security_locks' for model '%s' (structural lock finding present).",
                target_model,
            )
            if ctx.hop_budget_exhausted:
                logger.warning(
                    "Node [code_intelligence_agent]: CI_MAX_HOPS (%d) reached during "
                    "deterministic pre-dispatch (analyze_security_locks) -- breaking.",
                    ctx.hop_cap,
                )
                break
        except Exception as te:
            logger.error("Deterministic analyze_security_locks dispatch failed: %s", te)

    if any(k[0] == "analyze_security_locks" for k in ctx.seen_calls):
        ctx.system_prompt_suffix += (
            "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
            "analyze_security_locks has already been run for the target model(s) above "
            "because the question is approval/security-related; its output is already included "
            "in the tool observations. Do not call it again -- focus any further tool calls on "
            "what it does NOT cover (e.g. ir.rule / group-based record visibility via "
            "evaluate_record_rules)."
        )
