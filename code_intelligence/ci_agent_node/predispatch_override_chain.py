"""
code_intelligence/ci_agent_node/predispatch_override_chain.py

Deterministic pre-dispatch of 'analyze_method_override_chain', plus an
automatic follow-up 'read_source_code' for the first file:// link its
output cites. Extracted from the former ci_agent_node.py monolith
(refactor, see todo/contexte.txt). Behavior unchanged.
"""

import logging
import re
import time

from code_intelligence.security.gate import gate_observation
from .helpers import _truncate_observation, _tool_call_key
from code_intelligence.ci_agent_node.dispatch_context import DispatchContext

logger = logging.getLogger(__name__)


def dispatch_override_chain(ctx: DispatchContext) -> None:
    if not (ctx.concept.is_resolved and ctx.concept.resolved_models and not ctx.hop_budget_exhausted):
        return

    from .forced_dispatch_predicates import override_chain_targets

    override_tool = ctx.tool_map.get("analyze_method_override_chain")
    if override_tool is None:
        return

    for target_model, method_name in override_chain_targets(ctx.question, ctx.concept, ctx.G):
        call_key = _tool_call_key("analyze_method_override_chain", {"model_name": target_model, "method_name": method_name})
        if call_key in ctx.seen_calls:
            continue
        t0 = time.perf_counter()
        try:
            observation = str(override_tool.invoke({
                "model_name": target_model, "method_name": method_name,
            }))
            observation = _truncate_observation(observation, 2200)
            observation, omitted_list = gate_observation(
                tool_name="analyze_method_override_chain",
                model_name=target_model,
                observation=observation,
                G=ctx.G,
                user_groups=ctx.resolved_user_group_xmlids,
            )
            ctx.omitted_items.extend(omitted_list)
            ctx.record_observation(
                "analyze_method_override_chain",
                {"model_name": target_model, "method_name": method_name},
                observation, target_model, call_key, time.perf_counter() - t0,
            )
            logger.info(
                "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                "'analyze_method_override_chain' for '%s.%s' (approval wording "
                "+ real override cascade present).",
                target_model, method_name,
            )
            _match_link = re.search(r"\((file:///[^#\)]+)#L(\d+)-L(\d+)\)", observation)
            if _match_link and not ctx.hop_budget_exhausted:
                _read_tool = ctx.tool_map.get("read_source_code")
                if _read_tool is not None:
                    _fp = _match_link.group(1).replace("file://", "")
                    _ls = int(_match_link.group(2))
                    _le = int(_match_link.group(3))
                    _read_key = ("read_source_code", _fp, _ls, _le)
                    if _read_key not in ctx.seen_calls:
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
                            logger.info(
                                "Node [code_intelligence_agent]: Deterministic follow-up dispatch of "
                                "'read_source_code' for '%s' lines %d-%d.",
                                _fp, _ls, _le,
                            )
                        except Exception as _re:
                            logger.error("Deterministic read_source_code dispatch failed: %s", _re)
            if ctx.hop_budget_exhausted:
                logger.warning(
                    "Node [code_intelligence_agent]: CI_MAX_HOPS (%d) reached during "
                    "deterministic pre-dispatch (analyze_method_override_chain) -- breaking.",
                    ctx.hop_cap,
                )
                break
        except Exception as te:
            logger.error("Deterministic analyze_method_override_chain dispatch failed: %s", te)

    if any(k and k[0] == "analyze_method_override_chain" for k in ctx.seen_calls):
        ctx.system_prompt_suffix += (
            "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
            "analyze_method_override_chain has already been run for the "
            "overridden method(s) above because the question is approval-related "
            "and a real override cascade exists on the target model; its output is "
            "already included in the tool observations. Do not call it again -- if "
            "it flagged an unguarded super() OR an unchecked relational-field chain "
            "(CHAINE RELATIONNELLE NON VERIFIEE), that finding takes precedence over "
            "any single-module reading of the method. A relational-chain finding "
            "often names a SECOND threshold/condition (e.g. a higher amount that "
            "triggers an additional module's override on top of the first module's "
            "rule) -- when the question's stated amount clears both thresholds, both "
            "must be reported together, not only the first one encountered."
        )
