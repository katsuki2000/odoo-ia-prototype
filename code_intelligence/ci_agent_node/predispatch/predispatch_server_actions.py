"""
code_intelligence/ci_agent_node/predispatch_server_actions.py

Deterministic pre-dispatch of 'analyze_server_actions', plus an automatic
follow-up 'read_source_code' for every file:// link its output cites.
Extracted from the former ci_agent_node.py monolith (refactor, see
todo/contexte.txt). Behavior unchanged.
"""

import logging
import re
import time

from code_intelligence.security.gate import gate_observation
from code_intelligence.ci_agent_node.context.prompt_and_heuristics import (
    _truncate_observation,
    _tool_call_key,
)
from code_intelligence.ci_agent_node.context.dispatch_context import DispatchContext

logger = logging.getLogger(__name__)


def dispatch_server_actions(ctx: DispatchContext) -> None:
    if not (ctx.concept.is_resolved and ctx.concept.resolved_models and not ctx.hop_budget_exhausted):
        return

    from .forced_dispatch_predicates import server_actions_targets

    sa_tool = ctx.tool_map.get("analyze_server_actions")
    if sa_tool is None:
        return

    for target_model in server_actions_targets(ctx.question, ctx.concept, ctx.G):
        call_key = _tool_call_key("analyze_server_actions", {"model_name": target_model})
        if call_key in ctx.seen_calls:
            continue
        t0 = time.perf_counter()
        try:
            observation = str(sa_tool.invoke({"model_name": target_model}))
            observation = _truncate_observation(observation, 3000)
            observation, omitted_list = gate_observation(
                tool_name="analyze_server_actions",
                model_name=target_model,
                observation=observation,
                G=ctx.G,
                user_groups=ctx.resolved_user_group_xmlids,
            )
            ctx.omitted_items.extend(omitted_list)
            ctx.record_observation(
                "analyze_server_actions", {"model_name": target_model},
                observation, target_model, call_key, time.perf_counter() - t0,
            )
            logger.info(
                "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                "'analyze_server_actions' for model '%s' (automation/bypass "
                "wording + ServerAction nodes present).",
                target_model,
            )
            _match_links = re.findall(r"\((file:///[^#\)]+)#L(\d+)-L(\d+)\)", observation)
            for _m_link in _match_links:
                if ctx.hop_budget_exhausted:
                    break
                _read_tool = ctx.tool_map.get("read_source_code")
                if _read_tool is None:
                    continue
                _fp = _m_link[0].replace("file://", "")
                _ls = int(_m_link[1])
                _le = int(_m_link[2])
                _read_key = ("read_source_code", _fp, _ls, _le)
                if _read_key in ctx.seen_calls:
                    continue
                try:
                    _t_read = time.perf_counter()
                    _read_obs = str(_read_tool.invoke({
                        "filepath": _fp, "line_start": _ls, "line_end": _le,
                    }))
                    _read_obs = _truncate_observation(_read_obs, 4000)
                    ctx.record_observation(
                        "read_source_code",
                        {"filepath": _fp, "line_start": _ls, "line_end": _le},
                        _read_obs, target_model, _read_key, time.perf_counter() - _t_read,
                    )
                except Exception as re_err:
                    logger.error("Auto read_source_code after analyze_server_actions failed: %s", re_err)
            if ctx.hop_budget_exhausted:
                logger.warning(
                    "Node [code_intelligence_agent]: CI_MAX_HOPS (%d) reached during "
                    "deterministic pre-dispatch (analyze_server_actions) -- breaking.",
                    ctx.hop_cap,
                )
                break
        except Exception as te:
            logger.error("Deterministic analyze_server_actions dispatch failed: %s", te)

    if any(k[0] == "analyze_server_actions" for k in ctx.seen_calls):
        ctx.system_prompt_suffix += (
            "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
            "analyze_server_actions has already been run for the target model(s) "
            "above because the question suggests automation/bypass logic; its output "
            "is already included in the tool observations. Do not call it again."
        )
