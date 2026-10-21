"""Execute graph-grounded plans and request bounded follow-ups from observations."""

from copy import deepcopy
from dataclasses import dataclass, field
from types import SimpleNamespace

from .context import DispatchContext
from .capability_catalogue import build_capability_catalogue
from .capability_planner import generate_investigation_plan


@dataclass
class PlannedDispatchContext(DispatchContext):
    investigation_plan: dict = field(default_factory=dict)


def run_planned_investigation(ctx):
    from .tool_execution import execute_tool_calls
    plan = deepcopy(getattr(ctx, 'investigation_plan', None))
    if not plan or plan.get('execution_mode') != 'capability_v1':
        plan = generate_investigation_plan(ctx.question, ctx.concept, ctx.G, intent=ctx.intent).to_display_dict()
        ctx.llm_call_count += plan.get('planning_attempts', 0)
        ctx.llm_wait += plan.get('planning_wait_seconds', 0.0)
    ctx.investigation_plan = deepcopy(plan)
    attempted = set()
    pending = False
    while True:
        catalogue = {item.identifier: item for item in build_capability_catalogue(ctx.G, ctx.concept)}
        selected = {}
        for step in plan.get('steps', []):
            item = catalogue.get(step.get('capability_id'))
            if (item is None or step.get('action') != item.action.value
                    or step.get('target') != item.target or step.get('arguments') != item.arguments):
                ctx.system_prompt_suffix += '\nThe investigation plan no longer matches the graph; this round was not executed. Request a fresh plan.'
                return
            selected[item.identifier] = item
        roundAttempts = 0
        for item in selected.values():
            if ctx.hop_budget_exhausted:
                break
            if item.action.value not in ctx.tool_map:
                continue
            before = ctx.hop_count
            observationCount = len(ctx.tool_observations)
            execute_tool_calls(ctx, SimpleNamespace(tool_calls=[{
                'name': item.action.value, 'args': dict(item.arguments), 'id': 'plan_' + item.identifier,
            }]), [])
            if ctx.hop_count > before:
                attempted.add(item.identifier)
                roundAttempts += 1
            for index in range(observationCount, len(ctx.tool_observation_models)):
                if not ctx.tool_observation_models[index]:
                    ctx.tool_observation_models[index] = item.target
        pending = pending or bool(set(selected) - attempted)
        if not roundAttempts or ctx.hop_budget_exhausted or plan.get('source') == 'fallback_heuristic':
            break
        plan = generate_investigation_plan(ctx.question, ctx.concept, ctx.G, intent=ctx.intent,
            observations=ctx.tool_observations, excluded_ids=attempted,
            max_steps=ctx.hop_cap - ctx.hop_count).to_display_dict()
        ctx.llm_call_count += plan.get('planning_attempts', 0)
        ctx.llm_wait += plan.get('planning_wait_seconds', 0.0)
        ctx.investigation_plan['planning_attempts'] += plan.get('planning_attempts', 0)
        ctx.investigation_plan['planning_wait_seconds'] += plan.get('planning_wait_seconds', 0.0)
        ctx.investigation_plan['catalogue_truncated'] = ctx.investigation_plan.get('catalogue_truncated', False) or plan.get('catalogue_truncated', False)
        ctx.investigation_plan['rationale'] += '\n' + plan.get('rationale', '')
        for step in plan.get('steps', []):
            step['step_index'] = len(ctx.investigation_plan['steps']) + 1
            ctx.investigation_plan['steps'].append(step)
    if attempted:
        ctx.matched_dispatchers.append('semantic_capability_plan')
    ctx.system_prompt_suffix += (
        '\n[INVESTIGATION SCOPE]\n' + ctx.investigation_plan.get('rationale', '')
        + '\nOnly recorded observations are evidence. CRUD rights do not prove approval authority. '
        'Static absence does not establish absence of dynamic behavior. Do not invent method names or source ranges.'
    )
    if pending:
        ctx.system_prompt_suffix += '\nSome planned analyses were not executed (budget, unavailable tool or guard). Do not claim complete coverage.'
    if ctx.hop_budget_exhausted:
        ctx.system_prompt_suffix += '\nThe investigation budget is exhausted; further evidence was not assessed. State remaining uncertainty.'
    if not attempted:
        ctx.system_prompt_suffix += '\nNo safe capability was executed; clarify the subject or state the evidence gap.'
