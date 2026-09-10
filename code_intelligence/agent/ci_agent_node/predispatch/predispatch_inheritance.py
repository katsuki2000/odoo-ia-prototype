"""
code_intelligence/ci_agent_node/predispatch_inheritance.py

Deterministic pre-dispatch of 'trace_full_inheritance' and
'list_involved_modules' for inheritance-related questions, plus an
automatic follow-up 'read_source_code' for the most relevant file:// link
trace_full_inheritance cites. Extracted from the former ci_agent_node.py
monolith (refactor, see todo/contexte.txt). Behavior unchanged.
"""

import logging
import re
import time

from code_intelligence.agent.ci_agent_node.context.prompt_and_heuristics import (
    _truncate_observation,
    _tool_call_key,
)
from code_intelligence.agent.ci_agent_node.context.context_extractors import _question_is_inheritance_related
from code_intelligence.agent.ci_agent_node.context.dispatch_context import DispatchContext
from code_intelligence.agent.ci_agent_node.context.module_inference import rank_custom_modules_for_models

logger = logging.getLogger(__name__)


def dispatch_inheritance(ctx: DispatchContext) -> None:
    if not (
        ctx.concept.is_resolved
        and (ctx.concept.resolved_models or ctx.concept.resolved_modules)
        and _question_is_inheritance_related(ctx.question)
        and not ctx.hop_budget_exhausted
    ):
        return

    inherit_tool = ctx.tool_map.get("trace_full_inheritance")
    mod_tool = ctx.tool_map.get("list_involved_modules")

    target_mods_to_inspect = list(ctx.concept.resolved_modules)
    if not target_mods_to_inspect:
        candidate_mods = rank_custom_modules_for_models(ctx.G, ctx.concept.resolved_models, ctx.question)
        if candidate_mods:
            target_mods_to_inspect.append(candidate_mods[0])

    if mod_tool is not None:
        for t_mod in target_mods_to_inspect:
            if ctx.hop_budget_exhausted:
                break
            call_key = ("list_involved_modules", t_mod)
            if call_key in ctx.seen_calls:
                continue
            t0 = time.perf_counter()
            try:
                observation = str(mod_tool.invoke({"model_name": t_mod}))
                observation = _truncate_observation(observation, 3000)
                ctx.record_observation(
                    "list_involved_modules", {"model_name": t_mod},
                    observation, t_mod, call_key, time.perf_counter() - t0,
                )
                logger.info(
                    "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                    "'list_involved_modules' for module '%s'.",
                    t_mod,
                )
            except Exception as te:
                logger.error("Deterministic list_involved_modules dispatch for module failed: %s", te)

    for target_model in ctx.concept.resolved_models:
        if inherit_tool is not None and not ctx.hop_budget_exhausted:
            call_key = _tool_call_key("trace_full_inheritance", {"model_name": target_model})
            if call_key not in ctx.seen_calls:
                t0 = time.perf_counter()
                try:
                    observation = str(inherit_tool.invoke({"model_name": target_model}))
                    observation = _truncate_observation(observation, 3000)
                    ctx.record_observation(
                        "trace_full_inheritance", {"model_name": target_model},
                        observation, target_model, call_key, time.perf_counter() - t0,
                    )
                    logger.info(
                        "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                        "'trace_full_inheritance' for model '%s'.",
                        target_model,
                    )
                    from code_intelligence.agent.ci_agent_node.context.agent_tools import _is_custom_module_filepath
                    all_links = re.findall(r"\((file:///[^#\)]+)#L(\d+)-L(\d+)\)", observation)
                    chosen_link = None
                    if ctx.concept.resolved_modules:
                        for link_url, ls_s, le_s in all_links:
                            fp_clean = link_url.replace("file://", "")
                            if any(f"/{m}/" in fp_clean for m in ctx.concept.resolved_modules):
                                chosen_link = (link_url, ls_s, le_s)
                                break
                    if not chosen_link:
                        for link_url, ls_s, le_s in all_links:
                            fp_clean = link_url.replace("file://", "")
                            if _is_custom_module_filepath(fp_clean):
                                chosen_link = (link_url, ls_s, le_s)
                                break
                    if not chosen_link and all_links:
                        chosen_link = all_links[0]

                    if chosen_link:
                        _read_tool = ctx.tool_map.get("read_source_code")
                        if _read_tool is not None:
                            _fp = chosen_link[0].replace("file://", "")
                            _ls = max(1, int(chosen_link[1]))
                            _le = int(chosen_link[2])
                            try:
                                # NOTE: matches the original monolith exactly --
                                # this particular follow-up read does NOT cost a
                                # hop and is not added to seen_calls (unlike the
                                # analogous follow-ups in predispatch_server_
                                # actions.py/predispatch_override_chain.py).
                                # Preserved as-is (pure refactor, no behavior
                                # change); not something this mandate fixes.
                                _read_obs = str(_read_tool.invoke({
                                    "filepath": _fp,
                                    "line_start": _ls,
                                    "line_end": _le,
                                }))
                                _read_obs = _truncate_observation(_read_obs, 2500)
                                ctx.tool_observations.append(_read_obs)
                                ctx.tool_observation_models.append(target_model)
                                ctx.tool_observation_tools.append("read_source_code")
                                ctx.trace_logger.log_hop(
                                    trace_id=ctx.trace_id, hop_index=ctx.hop_index,
                                    tool_name="read_source_code",
                                    tool_args={"filepath": _fp, "line_start": _ls, "line_end": _le},
                                    observation=_read_obs, elapsed_ms=0,
                                )
                                ctx.hop_index += 1
                            except Exception as re_err:
                                logger.error("Auto read_source_code after trace_full_inheritance failed: %s", re_err)
                except Exception as te:
                    logger.error("Deterministic trace_full_inheritance dispatch failed: %s", te)
        if mod_tool is not None and not target_mods_to_inspect and not ctx.hop_budget_exhausted:
            call_key = _tool_call_key("list_involved_modules", {"model_name": target_model})
            if call_key not in ctx.seen_calls:
                t0 = time.perf_counter()
                try:
                    observation = str(mod_tool.invoke({"model_name": target_model}))
                    observation = _truncate_observation(observation, 3000)
                    ctx.record_observation(
                        "list_involved_modules", {"model_name": target_model},
                        observation, target_model, call_key, time.perf_counter() - t0,
                    )
                    logger.info(
                        "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                        "'list_involved_modules' for model '%s'.",
                        target_model,
                    )
                except Exception as te:
                    logger.error("Deterministic list_involved_modules dispatch failed: %s", te)

    if any(k and k[0] in {"trace_full_inheritance", "list_involved_modules"} for k in ctx.seen_calls):
        ctx.system_prompt_suffix += (
            "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
            "trace_full_inheritance and list_involved_modules have already been run for the "
            "target model(s) above; model hierarchy, mixins, and declaring/extending modules "
            "are already included in the tool observations. Do not call them again."
        )
