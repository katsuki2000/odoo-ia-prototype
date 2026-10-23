"""Execute ReAct tool calls and record only usable, authorized observations."""

import json
import logging
import time

from langchain_core.messages import ToolMessage

from code_intelligence.agent.context import (
    DEFAULT_OBSERVATION_CAP,
    MAX_TOTAL_OBSERVATION_CHARS,
    PER_TOOL_OBSERVATION_CAPS,
    DispatchContext,
    _truncate_observation_for_budget,
)
from code_intelligence.rules.common import NOT_FOUND_MARKER
from code_intelligence.rules.security_locks import gate_observation

logger = logging.getLogger(__name__)
DISCOVERY_TOOLS = frozenset({'search_system', 'resolve_technical_name'})
PRINCIPAL_SCOPED_TOOLS = frozenset({
    'evaluate_record_rules', 'button_execution_path', 'describe_navigation_path',
})


class UnknownPrincipalError(ValueError):
    pass


def _override_user_groups_arg(
    tool_name,
    arguments,
    requester_groups,
    security_principals=None,
    *,
    requester_groups_known=True,
):
    if tool_name not in PRINCIPAL_SCOPED_TOOLS:
        return arguments
    principalId = str(arguments.pop('principal_id', '') or '').strip()
    if principalId:
        if principalId not in (security_principals or {}):
            raise UnknownPrincipalError(principalId)
        groups = security_principals[principalId]
    else:
        groups = requester_groups if requester_groups_known else None
    arguments['user_groups_json'] = json.dumps(groups)
    return arguments


def execute_tool_calls(ctx: DispatchContext, ai_msg, messages: list) -> None:
    """Enforce identity, deduplication, budgets and evidence gates at execution."""
    for call in ai_msg.tool_calls:
        toolName, toolId = call.get('name', ''), call.get('id', '')
        analysisName = 'read_source_code' if toolName == 'read_source_fragment' else toolName
        arguments = dict(call.get('args') or {})
        if ctx.hop_budget_exhausted:
            messages.append(ToolMessage(content='Investigation tool budget exhausted.', tool_call_id=toolId))
            continue
        ctx.hop_count += 1
        if toolName not in ctx.tool_map:
            messages.append(ToolMessage(content='Tool unavailable.', tool_call_id=toolId))
            continue
        if toolName == 'who_has_access_to':
            arguments.setdefault('permission', 'all')
        try:
            arguments = _override_user_groups_arg(
                toolName,
                arguments,
                ctx.resolved_user_group_xmlids,
                ctx.security_principals,
                requester_groups_known=ctx.requester_groups_known,
            )
        except UnknownPrincipalError:
            messages.append(ToolMessage(
                content='Refused: undeclared security principal.', tool_call_id=toolId,
            ))
            continue
        callKey = (toolName, json.dumps(arguments, sort_keys=True, ensure_ascii=False))
        if callKey in ctx.seen_calls:
            messages.append(ToolMessage(
                content='Already executed; use the earlier observation.', tool_call_id=toolId,
            ))
            continue
        ctx.seen_calls.add(callKey)
        used = sum(map(len, ctx.tool_observations)) + getattr(ctx, 'discovery_chars', 0)
        if used >= MAX_TOTAL_OBSERVATION_CHARS:
            messages.append(ToolMessage(content='Observation budget exhausted.', tool_call_id=toolId))
            continue
        started = time.perf_counter()
        modelName = arguments.get('model_name') or arguments.get('model', '')
        try:
            observation = str(ctx.tool_map[toolName].invoke(arguments))
            if observation.lstrip().lower().startswith(('error', 'erreur', 'orm read refused:')):
                raise ValueError(f'Tool returned no usable evidence: {observation[:200]}')
            ruleResult = None
            if toolName == 'evaluate_record_rules':
                from code_intelligence.agent.tools.access import evaluate_rules_raw
                ruleResult = evaluate_rules_raw(
                    model_name=modelName,
                    permission=arguments.get('permission', 'read'),
                    user_groups_json=arguments.get('user_groups_json', 'null'),
                )
            if toolName not in getattr(ctx, 'orm_tool_names', set()):
                observation, omitted = gate_observation(
                    tool_name=analysisName,
                    model_name=modelName,
                    observation=observation,
                    G=ctx.G,
                    user_groups=ctx.resolved_user_group_xmlids or [],
                    rule_result=ruleResult,
                )
                ctx.omitted_items.extend(omitted)
            cap = min(
                6000 if toolName == 'search_system' else
                PER_TOOL_OBSERVATION_CAPS.get(analysisName, DEFAULT_OBSERVATION_CAP),
                MAX_TOTAL_OBSERVATION_CHARS - used,
            )
            observation = _truncate_observation_for_budget(ctx, observation, cap)
            if toolName in DISCOVERY_TOOLS:
                ctx.discovery_chars = getattr(ctx, 'discovery_chars', 0) + len(observation)
            elif NOT_FOUND_MARKER not in observation:
                ctx.tool_observations.append(observation)
                ctx.tool_observation_models.append(modelName)
                ctx.tool_observation_tools.append(analysisName)
                isRealModel = bool(modelName and ctx.G and ctx.G.has_node(f"model:{modelName}"))
                if isRealModel:
                    if modelName not in ctx.concept.resolved_models:
                        ctx.concept.resolved_models.append(modelName)
                    ctx.concept.is_resolved = True
                    ctx.concept.source_step = 'investigated_tools'
            messages.append(ToolMessage(content=observation, tool_call_id=toolId))
            elapsed = time.perf_counter() - started
            ctx.per_hop_times.append(elapsed)
            ctx.trace_logger.log_hop(
                trace_id=ctx.trace_id,
                hop_index=ctx.hop_index,
                tool_name=toolName,
                tool_args=arguments,
                observation=observation,
                elapsed_ms=elapsed * 1000,
            )
            ctx.hop_index += 1
        except Exception as error:
            logger.warning('Investigation tool %s failed (%s)', toolName, type(error).__name__)
            ctx.trace_logger.log_failure(
                ctx.trace_id, 'tool', error, tool_name=toolName, tool_args=arguments,
            )
            ctx.execution_failed = True
            messages.append(ToolMessage(
                content=f'Error executing {toolName}; no conclusion can be drawn from this failure.',
                tool_call_id=toolId,
            ))
