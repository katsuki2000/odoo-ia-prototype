"""
code_intelligence/ci_agent_node/predispatch_button.py

Deterministic pre-dispatch of 'button_execution_path' when the question
names a UI element (button/menu/field), plus an automatic follow-up
'read_source_code' for the file:// link its output cites. Extracted from
the former ci_agent_node.py monolith (refactor, see todo/contexte.txt).
Behavior unchanged.
"""

import json
import logging
import re
import time

from code_intelligence.agent.ci_agent_node.context.prompt_and_heuristics import (
    _truncate_observation,
    _tool_call_key,
)
from code_intelligence.agent.ci_agent_node.context.dispatch_context import DispatchContext
from code_intelligence.agent.ci_agent_node.context.ui_patterns import extract_ui_element_name

logger = logging.getLogger(__name__)


def dispatch_button_execution_path(ctx: DispatchContext) -> None:
    if not (ctx.concept.is_resolved and ctx.concept.resolved_models and not ctx.hop_budget_exhausted):
        return

    ui_name = extract_ui_element_name(ctx.question)
    if not ui_name:
        return

    btn_tool = ctx.tool_map.get("button_execution_path")
    if btn_tool is None:
        return

    for target_model in ctx.concept.resolved_models:
        call_key = _tool_call_key("button_execution_path", {"button_name": ui_name, "model_name": target_model})
        if call_key in ctx.seen_calls:
            continue
        try:
            t0 = time.perf_counter()
            dispatch_groups = json.dumps(ctx.resolved_user_group_xmlids or [])
            observation = str(btn_tool.invoke({
                "button_name": ui_name,
                "model_name": target_model,
                "user_groups_json": dispatch_groups,
            }))
            observation = _truncate_observation(observation, 3000)
            ctx.record_observation(
                "button_execution_path",
                {"button_name": ui_name, "model_name": target_model},
                observation, target_model, call_key, time.perf_counter() - t0,
            )
            logger.info(
                "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                "'button_execution_path' for element '%s' on model '%s'.",
                ui_name, target_model,
            )
            match_link = re.search(r"\((file:///[^#\)]+)#L(\d+)-L(\d+)\)", observation)
            if match_link and not ctx.hop_budget_exhausted:
                read_tool = ctx.tool_map.get("read_source_code")
                if read_tool is not None:
                    fp = match_link.group(1).replace("file://", "")
                    ls = int(match_link.group(2))
                    le = int(match_link.group(3))
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
                            logger.error("Auto read_source_code after button_execution_path failed: %s", re_err)
            if "not found" not in observation.lower():
                break
            if ctx.hop_budget_exhausted:
                break
        except Exception as te:
            logger.error("Deterministic button_execution_path dispatch failed: %s", te)
