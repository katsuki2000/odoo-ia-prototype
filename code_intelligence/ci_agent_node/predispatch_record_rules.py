"""
code_intelligence/ci_agent_node/predispatch_record_rules.py

Deterministic pre-dispatch of 'evaluate_record_rules', followed by an
injected 'can_view_amount_v2' deterministic fact when the question names an
amount. Extracted from the former ci_agent_node.py monolith (refactor, see
todo/contexte.txt). Behavior unchanged.
"""

import json as _json_dispatch
import logging
import time

from code_intelligence.authorization_gate import gate_observation
from code_intelligence.ci_helpers import (
    _truncate_observation,
    _tool_call_key,
    _question_is_access_related,
    _extract_amount,
    _extract_company_context,
    _infer_move_type_context,
    _format_can_view_amount_fact,
)
from code_intelligence.ci_agent_node.dispatch_context import DispatchContext

logger = logging.getLogger(__name__)


def dispatch_evaluate_record_rules(ctx: DispatchContext) -> None:
    if not (
        ctx.concept.is_resolved and ctx.concept.resolved_models
        and _question_is_access_related(ctx.question)
        and not ctx.hop_budget_exhausted
    ):
        return

    from code_intelligence.ci_agent_tools import evaluate_rules_raw

    amount_for_rules = _extract_amount(ctx.question)
    rule_tool = ctx.tool_map.get("evaluate_record_rules")
    if rule_tool is None:
        return

    for target_model in ctx.concept.resolved_models[:1]:
        call_key = _tool_call_key("evaluate_record_rules", {"model_name": target_model})
        if call_key in ctx.seen_calls:
            continue
        t0 = time.perf_counter()
        try:
            dispatch_groups = _json_dispatch.dumps(ctx.resolved_user_group_xmlids or [])
            observation = str(rule_tool.invoke({
                "model_name": target_model,
                "user_groups_json": dispatch_groups,
                "permission": "read",
            }))
            observation = _truncate_observation(observation, 3000)
            observation, omitted_list = gate_observation(
                tool_name="evaluate_record_rules",
                model_name=target_model,
                observation=observation,
                G=ctx.G,
                user_groups=ctx.resolved_user_group_xmlids,
            )
            ctx.omitted_items.extend(omitted_list)
            ctx.record_observation(
                "evaluate_record_rules",
                {"model_name": target_model, "permission": "read"},
                observation, target_model, call_key, time.perf_counter() - t0,
            )

            if amount_for_rules is not None:
                try:
                    dispatch_rule_result = evaluate_rules_raw(
                        model_name=target_model,
                        permission="read",
                        user_groups_json=dispatch_groups,
                    )
                    dispatch_context = {"amount": amount_for_rules}
                    dispatch_context.update(_extract_company_context(ctx.question))
                    dispatch_context.update(_infer_move_type_context(ctx.concept))
                    dispatch_can_view, dispatch_unresolved = (
                        dispatch_rule_result.can_view_amount_v2(dispatch_context)
                    )
                    ctx.tool_observations.append(
                        _format_can_view_amount_fact(
                            amount_for_rules, dispatch_can_view, dispatch_unresolved
                        )
                    )
                    ctx.tool_observation_models.append(target_model)
                    ctx.tool_observation_tools.append("can_view_amount_v2")
                    logger.info(
                        "Node [code_intelligence_agent]: Pre-dispatch "
                        "can_view_amount_v2 fact for model=%s, amount=%.0f, "
                        "result=%s, unresolved=%s, context=%s, "
                        "global=%d, group=%d.",
                        target_model, amount_for_rules, dispatch_can_view,
                        dispatch_unresolved, dispatch_context,
                        len(dispatch_rule_result.applied_global_rules),
                        len(dispatch_rule_result.applied_group_rules),
                    )
                except Exception as ve:
                    logger.error("Pre-dispatch can_view_amount_v2 injection failed: %s", ve)

            logger.info(
                "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                "'evaluate_record_rules' for model '%s' (access/rules-related question).",
                target_model,
            )
            if ctx.hop_budget_exhausted:
                logger.warning(
                    "Node [code_intelligence_agent]: CI_MAX_HOPS (%d) reached during "
                    "deterministic pre-dispatch (evaluate_record_rules) -- breaking.",
                    ctx.hop_cap,
                )
                break
        except Exception as te:
            logger.error("Deterministic evaluate_record_rules dispatch failed: %s", te)

    if any(k and k[0] == "evaluate_record_rules" for k in ctx.seen_calls):
        ctx.system_prompt_suffix += (
            "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
            "evaluate_record_rules has already been run for the target "
            "model(s) above and the can_view_amount_v2 deterministic fact has been "
            "injected. Do not call evaluate_record_rules again."
        )
