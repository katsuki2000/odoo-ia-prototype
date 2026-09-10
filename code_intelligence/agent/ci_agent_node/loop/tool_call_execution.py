"""
code_intelligence/ci_agent_node/tool_call_execution.py

Executes the tool calls an LLM tool-selection turn returned, one at a
time, appending observations to the shared DispatchContext exactly like
the deterministic pre-dispatch blocks do. Extracted from react_loop.py to
stay under the 300-line-per-file rule (refactor, see todo/contexte.txt).
Behavior unchanged.
"""

import logging
import time

from langchain_core.messages import ToolMessage

from code_intelligence.knowledge_rules.security.gate import gate_observation
from code_intelligence.agent.ci_agent_node.context.prompt_and_heuristics import (
    _truncate_observation,
    _tool_call_key,
)
from code_intelligence.agent.ci_agent_node.context.context_extractors import (
    _extract_amount,
    _extract_company_context,
    _infer_move_type_context,
)
from code_intelligence.agent.ci_agent_node.guards.can_view_verifier import _format_can_view_amount_fact
from code_intelligence.agent.ci_agent_node.guards.dispatch_utils import _override_user_groups_arg
from code_intelligence.agent.ci_agent_node.context.dispatch_context import DispatchContext

logger = logging.getLogger(__name__)


def execute_tool_calls(ctx: DispatchContext, ai_msg, messages: list) -> None:
    for tool_call in ai_msg.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        tool_id = tool_call["id"]

        if tool_name == "who_has_access_to" and "permission" not in tool_args:
            tool_args["permission"] = "all"

        tool_args = _override_user_groups_arg(tool_name, tool_args, ctx.resolved_user_group_xmlids)

        dup_call_key = _tool_call_key(tool_name, tool_args)
        if dup_call_key is not None and dup_call_key in ctx.seen_calls:
            logger.info(
                "Node [code_intelligence_agent]: LLM re-requested '%s' for %s "
                "despite a prior dispatch for the same target -- its observation "
                "is already present above, skipping re-execution.",
                tool_name, dup_call_key[1:],
            )
            messages.append(ToolMessage(
                content=(
                    f"'{tool_name}' a deja ete execute pour cette cible plus haut "
                    "dans cette analyse ; son observation est deja disponible "
                    "ci-dessus, ne la rappelle pas."
                ),
                tool_call_id=tool_id,
            ))
            continue

        logger.info("Node [code_intelligence_agent]: Single-Dispatch invoking '%s' with args %s", tool_name, tool_args)
        if tool_name not in ctx.tool_map:
            logger.warning(
                "Node [code_intelligence_agent]: LLM requested unknown tool '%s'.",
                tool_name,
            )
            messages.append(ToolMessage(
                content=f"Outil '{tool_name}' non disponible.",
                tool_call_id=tool_id,
            ))
        if tool_name in ctx.tool_map:
            t0 = time.perf_counter()
            try:
                observation = str(ctx.tool_map[tool_name].invoke(tool_args))

                observation_cap = (
                    6000 if tool_name == "read_source_code"
                    else 2200 if tool_name == "analyze_method_override_chain"
                    else 3500 if tool_name in {"analyze_server_actions", "analyze_data_constraints", "analyze_security_locks"}
                    else 2500
                )
                observation = _truncate_observation(observation, observation_cap)

                rule_result = None
                if tool_name == "evaluate_record_rules":
                    try:
                        from code_intelligence.agent.ci_agent_node.context.agent_tools import evaluate_rules_raw

                        rule_result = evaluate_rules_raw(
                            model_name=tool_args.get("model_name", ""),
                            permission=tool_args.get("permission", "read"),
                            user_groups_json=tool_args.get("user_groups_json", "[]"),
                        )
                    except Exception as ve:
                        logger.error("evaluate_rules_raw computation failed: %s", ve)

                observation, omitted_list = gate_observation(
                    tool_name=tool_name,
                    model_name=tool_args.get("model_name", ""),
                    observation=observation,
                    G=ctx.G,
                    user_groups=ctx.resolved_user_group_xmlids,
                    rule_result=rule_result,
                )
                ctx.omitted_items.extend(omitted_list)

                ctx.tool_observations.append(observation)
                ctx.tool_observation_models.append(tool_args.get("model_name", ""))
                ctx.tool_observation_tools.append(tool_name)

                messages.append(ToolMessage(content=observation, tool_call_id=tool_id))
                ctx.per_hop_times.append(time.perf_counter() - t0)
                ctx.hop_count += 1
                if dup_call_key is not None:
                    ctx.seen_calls.add(dup_call_key)

                ctx.trace_logger.log_hop(
                    trace_id=ctx.trace_id, hop_index=ctx.hop_index, tool_name=tool_name,
                    tool_args=tool_args, observation=observation,
                    elapsed_ms=ctx.per_hop_times[-1] * 1000,
                )
                ctx.hop_index += 1

                if ctx.hop_budget_exhausted:
                    logger.warning(
                        "Node [code_intelligence_agent]: CI_MAX_HOPS (%d) "
                        "reached -- breaking ReAct loop.", ctx.hop_cap,
                    )
                    break

                if tool_name == "evaluate_record_rules" and rule_result is not None:
                    amount = _extract_amount(ctx.question)
                    if amount is not None:
                        try:
                            context = {"amount": amount}
                            context.update(_extract_company_context(ctx.question))
                            context.update(_infer_move_type_context(ctx.concept))
                            can_view, unresolved_fields = rule_result.can_view_amount_v2(
                                context
                            )
                            ctx.tool_observations.append(
                                _format_can_view_amount_fact(amount, can_view, unresolved_fields)
                            )
                            ctx.tool_observation_models.append(tool_args.get("model_name", ""))
                            ctx.tool_observation_tools.append("can_view_amount_v2")
                            logger.info(
                                "Node [code_intelligence_agent]: Injected deterministic "
                                "can_view_amount_v2 fact for model=%s, amount=%.0f, "
                                "result=%s, unresolved=%s, context=%s, "
                                "global_rules_applied=%d, group_rules_applied=%d.",
                                tool_args.get("model_name", ""), amount, can_view,
                                unresolved_fields, context,
                                len(rule_result.applied_global_rules),
                                len(rule_result.applied_group_rules),
                            )
                        except Exception as ve:
                            logger.error(
                                "Deterministic can_view_amount injection failed: %s", ve
                            )
            except Exception as te:
                logger.error("Tool execution failed (%s): %s", tool_name, te)
                error_observation = f"Error executing {tool_name}: {str(te)}"
                ctx.tool_observations.append(error_observation)
                ctx.tool_observation_models.append(tool_args.get("model_name", ""))
                ctx.tool_observation_tools.append(tool_name)
                # ReAct-loop fix: surface the failure to the LLM too, so it
                # doesn't blindly repeat the exact same failing call on the
                # next iteration.
                messages.append(ToolMessage(content=error_observation, tool_call_id=tool_id))
