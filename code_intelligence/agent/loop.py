"""CI tool execution, ReAct synthesis and request orchestration."""

import json
import logging
import time
from langchain_core.messages import ToolMessage, SystemMessage, HumanMessage
from code_intelligence.rules.security_locks import gate_observation
from code_intelligence.agent.context import (
    _truncate_observation_for_budget, _tool_call_key, PER_TOOL_OBSERVATION_CAPS,
    DEFAULT_OBSERVATION_CAP, DispatchContext, CI_MAX_HOPS,
    _resolve_user_group_xmlids, build_early_refusal_response,
)
from code_intelligence.agent.context_extractors import (
    _extract_amount, _extract_company_context, _infer_move_type_context, _question_is_inheritance_related,
)
from code_intelligence.agent.can_view_verifier import _format_can_view_amount_fact
from code_intelligence.agent.dispatch_guards import (
    _override_user_groups_arg, UnknownPrincipalError, _strip_group_resolution_noise,
    _build_dynamic_uncertainty_answer, _maybe_build_application_layer_reminder, _rank_and_cap_resolved_models,
)
from code_intelligence.rules.structure import _extract_module_extended_models, _answer_lacks_extension_coverage
from core.llm.llm_client import get_chat_llm, invoke_with_rate_limit as _invoke_with_rate_limit
from core.output import _detect_any_degenerate_repetition, _strip_any_degenerate_repetition
from core.guardrails import OUT_OF_SCOPE_ANSWER, REACT_RECURSION_LIMIT, is_massive_extraction_request, is_out_of_scope, is_prompt_injection
from core.state import RAGState
from code_intelligence.graph import get_code_intelligence_graph
from code_intelligence.agent.resolution.turn import resolve_turn
from code_intelligence.agent.prompts import CI_SYSTEM_PROMPT, build_synthesis_prompt, build_business_context_prompt, build_persona_prompt_block
from code_intelligence.agent.predispatch import run_predispatch_chain
from .postprocess import build_final_response
from .capability_dispatch import PlannedDispatchContext

logger = logging.getLogger(__name__)
SYNTHESIS_UNAVAILABLE_ANSWER = (
    "Le modèle de rédaction est indisponible pour le moment : la réponse n'a pas pu être "
    "générée. Les éléments trouvés dans le graphe restent consultables dans les sources. Réessayez dans un instant."
)


def _should_bypass_synthesis(tool_names: list[str]) -> bool:
    return tool_names == ['analyze_data_constraints']


def execute_tool_calls(ctx: DispatchContext, ai_msg, messages: list) -> None:
    for call in ai_msg.tool_calls:
        if ctx.hop_budget_exhausted:
            break
        toolName, arguments, toolId = call['name'], call['args'], call['id']
        if toolName == 'who_has_access_to' and 'permission' not in arguments:
            arguments['permission'] = 'all'
        if toolName == 'describe_navigation_path':
            arguments = dict(arguments, user_groups_json=json.dumps(
                ctx.resolved_user_group_xmlids if ctx.requester_groups_known else None))
        try:
            arguments = _override_user_groups_arg(toolName, arguments, ctx.resolved_user_group_xmlids,
                ctx.security_principals, requester_groups_known=ctx.requester_groups_known)
        except UnknownPrincipalError as error:
            messages.append(ToolMessage(content=f'Appel refuse : {error}', tool_call_id=toolId))
            continue
        callKey = _tool_call_key(toolName, arguments) or (toolName, json.dumps(arguments, sort_keys=True))
        if callKey is not None and callKey in ctx.seen_calls:
            messages.append(ToolMessage(content=f"'{toolName}' a deja ete execute pour cette cible ; son observation est disponible plus haut.", tool_call_id=toolId))
            continue
        if toolName not in ctx.tool_map:
            messages.append(ToolMessage(content=f"Outil '{toolName}' non disponible.", tool_call_id=toolId))
            continue
        started = time.perf_counter()
        ctx.hop_count += 1
        ctx.seen_calls.add(callKey)
        try:
            observation = str(ctx.tool_map[toolName].invoke(arguments))
            observation = _truncate_observation_for_budget(ctx, observation, PER_TOOL_OBSERVATION_CAPS.get(toolName, DEFAULT_OBSERVATION_CAP))
            ruleResult = None
            if toolName == 'evaluate_record_rules':
                try:
                    from code_intelligence.agent.tools import evaluate_rules_raw
                    ruleResult = evaluate_rules_raw(model_name=arguments.get('model_name', ''), permission=arguments.get('permission', 'read'), user_groups_json=arguments.get('user_groups_json', '[]'))
                except Exception as error:
                    logger.error('Rule evaluation failed: %s', error)
            observation, omitted = gate_observation(tool_name=toolName, model_name=arguments.get('model_name', ''),
                observation=observation, G=ctx.G, user_groups=ctx.resolved_user_group_xmlids or [], rule_result=ruleResult)
            ctx.omitted_items.extend(omitted)
            ctx.tool_observations.append(observation)
            ctx.tool_observation_models.append(arguments.get('model_name', ''))
            ctx.tool_observation_tools.append(toolName)
            messages.append(ToolMessage(content=observation, tool_call_id=toolId))
            ctx.per_hop_times.append(time.perf_counter() - started)
            if callKey is not None:
                ctx.seen_calls.add(callKey)
            ctx.trace_logger.log_hop(trace_id=ctx.trace_id, hop_index=ctx.hop_index, tool_name=toolName,
                tool_args=arguments, observation=observation, elapsed_ms=ctx.per_hop_times[-1] * 1000)
            ctx.hop_index += 1
            if ctx.hop_budget_exhausted:
                break
            if toolName == 'evaluate_record_rules' and ruleResult is not None:
                amount = _extract_amount(ctx.question)
                if amount is not None:
                    try:
                        context = {'amount': amount}
                        context.update(_extract_company_context(ctx.question))
                        context.update(_infer_move_type_context(ctx.concept))
                        canView, unresolved = ruleResult.can_view_amount_v2(context)
                        ctx.tool_observations.append(_format_can_view_amount_fact(amount, canView, unresolved))
                        ctx.tool_observation_models.append(arguments.get('model_name', ''))
                        ctx.tool_observation_tools.append('can_view_amount_v2')
                    except Exception as error:
                        logger.error('Amount visibility evaluation failed: %s', error)
        except Exception as error:
            observation = f'Error executing {toolName}: {str(error)}'
            ctx.tool_observations.append(observation)
            ctx.tool_observation_models.append(arguments.get('model_name', ''))
            ctx.tool_observation_tools.append(toolName)
            messages.append(ToolMessage(content=observation, tool_call_id=toolId))


def run_react_loop(ctx: DispatchContext, system_prompt: str, chat_history: list, react_recursion_limit: int,
                   tool_llm_box: list, rebuild_tool_llm, *, allow_tool_selection: bool = True) -> str:
    messages = [SystemMessage(content=system_prompt), *chat_history[-6:], HumanMessage(content=ctx.question)]
    answer = _build_dynamic_uncertainty_answer('\n\n'.join(ctx.tool_observations)) if ctx.tool_observations else None
    if not answer and not ctx.security_distinction_reminder_sent:
        reminder = _maybe_build_application_layer_reminder(ctx.question, ctx.tool_observation_tools)
        if reminder:
            messages.append(SystemMessage(content=reminder))
            ctx.security_distinction_reminder_sent = True
    for _ in range(0 if answer else react_recursion_limit):
        response = None
        if allow_tool_selection and not ctx.hop_budget_exhausted:
            try:
                response, wait = _invoke_with_rate_limit(tool_llm_box[0], messages, rebuild_llm=rebuild_tool_llm)
                ctx.llm_call_count += 1
                ctx.llm_wait += wait
            except Exception as error:
                ctx.llm_call_count += 1
                logger.error('Tool selection failed: %s', error)
        if response and getattr(response, 'tool_calls', None):
            messages.append(response)
            execute_tool_calls(ctx, response, messages)
            if not ctx.security_distinction_reminder_sent:
                reminder = _maybe_build_application_layer_reminder(ctx.question, ctx.tool_observation_tools)
                if reminder:
                    messages.append(SystemMessage(content=reminder))
                    ctx.security_distinction_reminder_sent = True
        elif response and response.content:
            answer = response.content
        if not answer and ctx.tool_observations and _should_bypass_synthesis(ctx.tool_observation_tools):
            answer = ctx.tool_observations[0]
        if not answer:
            if not ctx.tool_observations:
                answer = "Je n'ai pas de données disponibles pour répondre à cette question."
            else:
                ctx.tool_observations, ctx.tool_observation_models, ctx.tool_observation_tools = _strip_group_resolution_noise(
                    ctx.tool_observations, ctx.resolved_user_group_xmlids, ctx.tool_observation_models, ctx.tool_observation_tools)
                prompt = build_synthesis_prompt(ctx.question, ctx.tool_observations, ctx.tool_observation_tools, security_principals=ctx.security_principals)
                try:
                    plain = [None]
                    def rebuildPlain():
                        plain[0] = get_chat_llm(temperature=0.0, max_retries=0, max_tokens=4096,
                            model_kwargs={'frequency_penalty': 0.3, 'presence_penalty': 0.2})
                        return plain[0]
                    rebuildPlain()
                    started = time.perf_counter()
                    result, wait = _invoke_with_rate_limit(plain[0], [HumanMessage(content=prompt)], rebuild_llm=rebuildPlain)
                    ctx.llm_call_count += 1
                    ctx.llm_wait += wait
                    ctx.synthesis_time = time.perf_counter() - started
                    answer = result.content
                    if _detect_any_degenerate_repetition(answer):
                        try:
                            retry, wait = _invoke_with_rate_limit(plain[0], [HumanMessage(content=prompt), SystemMessage(content=
                                'Do not repeat a word or phrase more than twice. Give a concise, non-repetitive answer.')], max_retries=2, rebuild_llm=rebuildPlain)
                            ctx.llm_call_count += 1
                            ctx.llm_wait += wait
                            answer = retry.content if not _detect_any_degenerate_repetition(retry.content) else _strip_any_degenerate_repetition(answer)
                        except Exception:
                            answer = _strip_any_degenerate_repetition(answer)
                    try:
                        models = _extract_module_extended_models('\n\n'.join(ctx.tool_observations))
                        if models and _question_is_inheritance_related(ctx.question) and _answer_lacks_extension_coverage(answer, models):
                            retry, wait = _invoke_with_rate_limit(plain[0], [HumanMessage(content=prompt), SystemMessage(content=
                                f'The tools established that this module extends these models: {", ".join(models)}. Explain and cite that coverage without contradicting the findings.')], max_retries=2, rebuild_llm=rebuildPlain)
                            ctx.llm_call_count += 1
                            ctx.llm_wait += wait
                            if not _answer_lacks_extension_coverage(retry.content, models):
                                answer = retry.content
                    except Exception as error:
                        logger.error('Extension coverage retry failed: %s', error)
                except Exception as error:
                    logger.error('Synthesis failed: %s', error)
                    answer = SYNTHESIS_UNAVAILABLE_ANSWER
        if answer:
            break
    return answer


class CodeIntelligenceAgentRunner:
    def __init__(self, state: RAGState):
        self.state = state

    def run(self) -> dict:
        state = self.state
        started = time.time()
        question = state.get('question', '').strip()
        history = state.get('chat_history', [])
        from core.session.reasoning_trace_logger import ReasoningTraceLogger, new_trace_id
        traceId, traceLogger = new_trace_id(), ReasoningTraceLogger()
        if is_out_of_scope(question):
            return build_early_refusal_response(OUT_OF_SCOPE_ANSWER, traceLogger, traceId, question, started, state, CI_MAX_HOPS)
        from config.settings import MAX_MODELS_PER_QUERY, MASSIVE_EXTRACTION_REFUSAL_MSG, PROMPT_INJECTION_REFUSAL_MSG
        if is_prompt_injection(question):
            return build_early_refusal_response(PROMPT_INJECTION_REFUSAL_MSG, traceLogger, traceId, question, started, state, CI_MAX_HOPS)
        if is_massive_extraction_request(question):
            return build_early_refusal_response(MASSIVE_EXTRACTION_REFUSAL_MSG, traceLogger, traceId, question, started, state, CI_MAX_HOPS)
        language = state.get('language')
        graph = get_code_intelligence_graph(translation_languages=[language] if language else None, request_language=language)
        from code_intelligence.agent.tools import ALL_CI_TOOLS
        from code_intelligence.agent.tool_helpers import set_graph_ref, set_llm_ref, set_current_question
        set_graph_ref(graph)
        set_current_question(question)
        missing = object()
        rawGroups = state.get('user_groups', missing)
        if rawGroups is missing:
            groups, groupsKnown = None, False
        else:
            rawGroups = list(rawGroups or [])
            groups = _resolve_user_group_xmlids(rawGroups)
            groupsKnown = len(groups) == len(rawGroups) and state.get('user_groups_complete') is not False
        principals = {key: _resolve_user_group_xmlids(value.get('group_xmlids', []))
                      for key, value in (state.get('security_principals') or {}).items()}
        llm = get_chat_llm(temperature=0.0, max_retries=0, max_tokens=1024, model_kwargs={'parallel_tool_calls': False})
        set_llm_ref(llm)
        toolLlm = [llm.bind_tools(ALL_CI_TOOLS)]
        def rebuildTool():
            fresh = get_chat_llm(temperature=0.0, max_retries=0, max_tokens=1024, model_kwargs={'parallel_tool_calls': False})
            set_llm_ref(fresh)
            toolLlm[0] = fresh.bind_tools(ALL_CI_TOOLS)
            return toolLlm[0]
        resolverStarted = time.perf_counter()
        concept, reused = resolve_turn(question, graph, state, language=language, llm=llm)
        resolverTime = time.perf_counter() - resolverStarted
        resolvedBefore = concept.is_resolved
        from core.evidence.evidence_check import check_evidence
        evidence = check_evidence(concept, resolvedBefore, state)
        if not reused or (state.get('investigation_plan') or {}).get('execution_mode') != 'capability_v1':
            from code_intelligence.agent.investigation_planner import validate_plan_against_route
            from code_intelligence.agent.capability_planner import generate_investigation_plan
            from code_intelligence.agent.investigation_llm import resolve_question_intent
            intent = resolve_question_intent(question, concept, graph).intent
            plan = generate_investigation_plan(question=question, resolved_concept=concept, G=graph, user_groups=state.get('user_groups'), intent=intent)
            state = dict(state, investigation_plan=validate_plan_against_route(plan, state.get('route')).to_display_dict())
        if concept.is_resolved and concept.resolved_modules and not concept.resolved_models:
            for module in concept.resolved_modules:
                moduleNode = 'module:' + module
                if moduleNode in graph:
                    for source, _target, edge in graph.in_edges(moduleNode, data=True):
                        if source.startswith('model:') and edge.get('edge_type') == 'DEFINED_IN' and edge.get('role', 'declares') == 'declares':
                            model = source.removeprefix('model:')
                            if model not in concept.resolved_models:
                                concept.resolved_models.append(model)
        if len(concept.resolved_models) > MAX_MODELS_PER_QUERY:
            concept.resolved_models = _rank_and_cap_resolved_models(question, concept.resolved_models, MAX_MODELS_PER_QUERY)
        ctx = PlannedDispatchContext(G=graph, concept=concept, question=question, tool_map={tool.name: tool for tool in ALL_CI_TOOLS},
            resolved_user_group_xmlids=groups, requester_groups_known=groupsKnown, trace_logger=traceLogger, trace_id=traceId,
            hop_cap=CI_MAX_HOPS, security_principals=principals, intent=(state.get('investigation_plan') or {}).get('intent'),
            investigation_plan=state.get('investigation_plan') or {})
        ctx.llm_call_count = int(concept.diagnostics.get('arbitration_attempts', '0'))
        ctx.llm_wait += float(concept.diagnostics.get('arbitration_wait_seconds', '0'))
        ctx.llm_call_count += ctx.investigation_plan.get('planning_attempts', 0)
        ctx.llm_wait += ctx.investigation_plan.get('planning_wait_seconds', 0.0)
        system = CI_SYSTEM_PROMPT + build_business_context_prompt(question, concept, graph) + build_persona_prompt_block(ctx.security_principals)
        run_predispatch_chain(ctx)
        state = dict(state, investigation_plan=ctx.investigation_plan)
        traceLogger.log_routing(traceId, ctx.matched_dispatchers)
        system += ctx.system_prompt_suffix
        if ctx.tool_observations:
            system += '\n\n[PRIOR TOOL OBSERVATIONS]\n' + '\n---\n'.join(ctx.tool_observations)
        answer = run_react_loop(ctx, system, history, REACT_RECURSION_LIMIT, toolLlm, rebuildTool, allow_tool_selection=False)
        if ctx.requester_acl_verdicts:
            from code_intelligence.agent.predispatch_access import build_requester_acl_answer
            deterministic = build_requester_acl_answer(question, language or '', ctx.requester_acl_verdicts)
            if deterministic:
                answer = deterministic
        return build_final_response(ctx, answer, state, started, resolverTime, evidence)


def code_intelligence_agent(state: RAGState) -> dict:
    if state.get("source_mode") == "documentation":
        # Defensive compatibility guard; the active graph routes documentation
        # directly to retrieval/generation before entering this agent.
        return {"timing": state.get("timing", {})}
    return CodeIntelligenceAgentRunner(state).run()
