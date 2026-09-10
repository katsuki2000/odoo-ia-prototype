"""
code_intelligence/ci_agent_node/predispatch_constraints.py

Deterministic pre-dispatch of 'analyze_data_constraints' for constraint-
related questions, plus an automatic follow-up 'read_source_code' around
any odoo-static-exclusion-filter finding. Extracted from the former
ci_agent_node.py monolith (refactor, see todo/contexte.txt). Behavior
unchanged.
"""

import logging
import re
import time

from .prompt_and_heuristics import (
    _truncate_observation,
    _tool_call_key,
)
from .context_extractors import _question_is_constraint_related
from code_intelligence.ci_agent_node.dispatch_context import DispatchContext

logger = logging.getLogger(__name__)


def dispatch_analyze_data_constraints(ctx: DispatchContext) -> None:
    if not (
        ctx.concept.is_resolved and ctx.concept.resolved_models
        and _question_is_constraint_related(ctx.question)
        and not ctx.hop_budget_exhausted
    ):
        return

    constraint_tool = ctx.tool_map.get("analyze_data_constraints")
    if constraint_tool is None:
        return

    for target_model in ctx.concept.resolved_models:
        call_key = _tool_call_key("analyze_data_constraints", {"model_name": target_model})
        if call_key in ctx.seen_calls:
            continue
        t0 = time.perf_counter()
        try:
            observation = str(constraint_tool.invoke({"model_name": target_model}))
            observation = _truncate_observation(observation, 3500)
            ctx.record_observation(
                "analyze_data_constraints", {"model_name": target_model},
                observation, target_model, call_key, time.perf_counter() - t0,
            )
            logger.info(
                "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                "'analyze_data_constraints' for model '%s'.",
                target_model,
            )
            if "odoo-static-exclusion-filter" in observation and not ctx.hop_budget_exhausted:
                match_link = re.search(
                    r"\(file://([^#\)]+)#L(\d+)-L(\d+)\)\s+\(odoo-static-exclusion-filter\)",
                    observation,
                )
                if match_link:
                    read_tool = ctx.tool_map.get("read_source_code")
                    if read_tool is not None:
                        fp = match_link.group(1)
                        ls = max(1, int(match_link.group(2)) - 5)
                        le = int(match_link.group(3)) + 35
                        read_key = ("read_source_code", fp, ls, le)
                        if read_key not in ctx.seen_calls:
                            try:
                                t_read = time.perf_counter()
                                read_obs = str(read_tool.invoke({
                                    "filepath": fp, "line_start": ls, "line_end": le,
                                }))
                                read_obs = _truncate_observation(read_obs, 4000)
                                ctx.record_observation(
                                    "read_source_code",
                                    {"filepath": fp, "line_start": ls, "line_end": le},
                                    read_obs, target_model, read_key, time.perf_counter() - t_read,
                                )
                            except Exception as re_err:
                                logger.error("Auto read_source_code after analyze_data_constraints failed: %s", re_err)
            if ctx.hop_budget_exhausted:
                break
        except Exception as te:
            logger.error("Deterministic analyze_data_constraints dispatch failed: %s", te)

    if any(k and k[0] == "analyze_data_constraints" for k in ctx.seen_calls):
        ctx.system_prompt_suffix += (
            "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
            "analyze_data_constraints has already been run for the target model(s) above; "
            "its SQL uniqueness and relational domain rules are already included in the "
            "tool observations. Do not call analyze_data_constraints again."
        )
