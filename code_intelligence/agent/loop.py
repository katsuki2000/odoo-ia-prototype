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

from code_intelligence.rules.security_locks import gate_observation
from code_intelligence.agent.context import (
    _truncate_observation,
    _tool_call_key,
)
from code_intelligence.agent.context_extractors import (
    _extract_amount,
    _extract_company_context,
    _infer_move_type_context,
)
from code_intelligence.agent.can_view_verifier import _format_can_view_amount_fact
from code_intelligence.agent.dispatch_guards import _override_user_groups_arg
from code_intelligence.agent.context import DispatchContext

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
                    9000 if tool_name == "read_source_code"
                    else 2200 if tool_name == "analyze_method_override_chain"
                    else 3500 if tool_name in {"analyze_server_actions", "analyze_data_constraints", "analyze_security_locks"}
                    else 2500
                )
                observation = _truncate_observation(observation, observation_cap)

                rule_result = None
                if tool_name == "evaluate_record_rules":
                    try:
                        from code_intelligence.agent.tools import evaluate_rules_raw

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

# ── ReAct Loop ─────────────────────────────────────────────────────────

"""
code_intelligence/ci_agent_node/react_loop.py

The CI agent's single-pass composite ReAct loop (tool-selection turn +
tool execution + synthesis turn), plus the degenerate-repetition retry on
the synthesized answer.
"""

import logging
import time

from langchain_core.messages import SystemMessage, HumanMessage

from code_intelligence.agent.dispatch_guards import (
    _strip_group_resolution_noise,
    _force_dynamic_uncertainty_answer,
)
from core.llm.llm_client import get_chat_llm, invoke_with_rate_limit as _invoke_with_rate_limit
from core.output import (
    _detect_any_degenerate_repetition,
    _strip_any_degenerate_repetition,
)
from code_intelligence.agent.context import DispatchContext
from code_intelligence.agent.prompts import build_synthesis_prompt

logger = logging.getLogger(__name__)


def run_react_loop(
    ctx: DispatchContext,
    system_prompt: str,
    chat_history: list,
    react_recursion_limit: int,
    tool_llm_box: list,
    rebuild_tool_llm,
) -> str:
    messages = [
        SystemMessage(content=system_prompt),
        *chat_history[-6:],
        HumanMessage(content=ctx.question),
    ]

    final_answer = None
    if ctx.tool_observations:
        final_answer = _force_dynamic_uncertainty_answer(
            ctx.question, "\n\n".join(ctx.tool_observations),
        )

    for _ in range(0 if final_answer else react_recursion_limit):
        # the deterministic pre-dispatch blocks each break their OWN loop once hop_count reaches the cap, but nothing previously stopped THIS ReAct loop from still invoking llm_with_tools for at least one more iteration when the hop budget was already exhausted by pre-dispatch. Skipping the tool-selection call outright once the budget is already spent closes the gap at its root: no second call is ever issued, nothing to reconcile after the fact.
        if ctx.hop_budget_exhausted:
            logger.info(
                "Node [code_intelligence_agent]: hop budget already "
                "exhausted (%d/%d) before this ReAct iteration -- "
                "skipping tool-selection call, synthesizing directly "
                "from the tool observations already gathered.",
                ctx.hop_count, ctx.hop_cap,
            )
            ai_msg = None
        else:
            try:
                ai_msg, wait = _invoke_with_rate_limit(
                    tool_llm_box[0], messages, rebuild_llm=rebuild_tool_llm,
                )
                ctx.llm_call_count += 1  # tool-selection call
                ctx.groq_wait += wait
            except Exception as e:
                ctx.llm_call_count += 1  # attempt still counts against the LLM-call budget
                logger.error("LLM tool selection failed: %s", e)
                ai_msg = None

        if ai_msg and getattr(ai_msg, "tool_calls", None):
            messages.append(ai_msg)
            execute_tool_calls(ctx, ai_msg, messages)
        elif ai_msg and ai_msg.content:
            final_answer = ai_msg.content

        # Synthesize clean final answer from composite tool output
        if not final_answer:
            if ctx.tool_observations:
                # trip 'could not be resolved' noise from who_has_access_to before it reaches the synthesis LLM when the real-auth override has already injected the demandeur's real groups into evaluate_record_rules and a deterministic can_view_amount fact is present.
                ctx.tool_observations, ctx.tool_observation_models, ctx.tool_observation_tools = _strip_group_resolution_noise(
                    ctx.tool_observations, ctx.resolved_user_group_xmlids,
                    ctx.tool_observation_models, ctx.tool_observation_tools,
                )
                synthesis_prompt = build_synthesis_prompt(ctx.question, ctx.tool_observations)
                try:
                    plain_llm_box = [None]

                    def _rebuild_plain_llm():
                        plain_llm_box[0] = get_chat_llm(
                            temperature=0.0, max_retries=0, max_tokens=4096,
                            model_kwargs={"frequency_penalty": 0.3, "presence_penalty": 0.2},
                        )
                        return plain_llm_box[0]

                    _rebuild_plain_llm()
                    t_synth = time.perf_counter()
                    final_resp, synth_wait = _invoke_with_rate_limit(
                        plain_llm_box[0], [HumanMessage(content=synthesis_prompt)],
                        rebuild_llm=_rebuild_plain_llm,
                    )
                    ctx.llm_call_count += 1  # synthesis call
                    ctx.groq_wait += synth_wait
                    final_answer = final_resp.content
                    ctx.synthesis_time = time.perf_counter() - t_synth
                    if _detect_any_degenerate_repetition(final_answer):
                        logger.warning(
                            "Node [code_intelligence_agent]: degenerate repetition detected in "
                            "synthesis output (%d chars) -- retrying once with an explicit "
                            "anti-repetition instruction before falling back to stripping it.",
                            len(final_answer),
                        )
                        retry_messages = [
                            HumanMessage(content=synthesis_prompt),
                            SystemMessage(content=(
                                "RAPPEL STRICT : ta r\u00e9ponse pr\u00e9c\u00e9dente contenait une "
                                "r\u00e9p\u00e9tition d\u00e9g\u00e9n\u00e9r\u00e9e (le m\u00eame mot ou groupe "
                                "de mots r\u00e9p\u00e9t\u00e9 des dizaines de fois de suite). Ne r\u00e9p\u00e8te "
                                "JAMAIS un mot ou groupe de mots plus de 2-3 fois de suite. Si tu "
                                "n'as rien de nouveau \u00e0 dire sur un point, passe au suivant ou "
                                "termine ta phrase."
                            )),
                        ]
                        try:
                            retry_resp, retry_wait = _invoke_with_rate_limit(
                                plain_llm_box[0], retry_messages, max_retries=2,
                                rebuild_llm=_rebuild_plain_llm,
                            )
                            ctx.llm_call_count += 1  # anti-repetition retry call
                            ctx.groq_wait += retry_wait
                            if not _detect_any_degenerate_repetition(retry_resp.content):
                                final_answer = retry_resp.content
                            else:
                                logger.error(
                                    "Node [code_intelligence_agent]: synthesis still degenerate "
                                    "after retry -- stripping the repeated run instead of shipping it."
                                )
                                final_answer = _strip_any_degenerate_repetition(final_answer)
                        except Exception as retry_e:
                            logger.error("Anti-repetition retry failed: %s", retry_e)
                            final_answer = _strip_any_degenerate_repetition(final_answer)
                except Exception as e:
                    logger.error("Synthesis failed: %s", e)
                    final_answer = "\n\n".join(ctx.tool_observations)
            else:
                final_answer = "Je n'ai pas de données disponibles pour répondre à cette question."

        if final_answer:
            break

    return final_answer

# ── Runner ─────────────────────────────────────────────────────────────

"""
code_intelligence/ci_agent_node/runner.py

CodeIntelligenceAgentRunner: orchestrates the CI agent turn end-to-end --
early refusals, graph/LLM setup, business-term resolution, the
deterministic pre-dispatch chain, the ReAct loop, and final response
assembly. Extracted from the former ci_agent_node.py monolith (refactor,
see todo/contexte.txt). Behavior unchanged.
"""

import logging
import time

from core.routing.routing import (
    RAGState, _is_out_of_scope, OUT_OF_SCOPE_ANSWER,
    _is_massive_extraction_request, _is_prompt_injection,
    REACT_RECURSION_LIMIT,
)
from core.llm.llm_client import get_chat_llm
from code_intelligence.graph import get_code_intelligence_graph
from code_intelligence.agent.resolver import resolve_business_term
from code_intelligence.agent.context import CI_MAX_HOPS
from code_intelligence.agent.dispatch_guards import _rank_and_cap_resolved_models
from code_intelligence.agent.context import _resolve_user_group_xmlids
from code_intelligence.agent.context import build_early_refusal_response
from code_intelligence.agent.context import DispatchContext
from code_intelligence.agent.prompts import CI_SYSTEM_PROMPT, build_business_context_prompt
from code_intelligence.agent.predispatch import run_predispatch_chain
from .postprocess import build_final_response

logger = logging.getLogger(__name__)


class CodeIntelligenceAgentRunner:
    def __init__(self, state: RAGState):
        self.state = state

    def run(self) -> dict:
        state = self.state
        start_time = time.time()

        question = state.get("question", "").strip()
        chat_history = state.get("chat_history", [])
        logger.info("Node [code_intelligence_agent]: Starting ReAct loop for: %s", question)

        from core.session.reasoning_trace_logger import ReasoningTraceLogger, new_trace_id
        trace_id = new_trace_id()
        trace_logger = ReasoningTraceLogger()

        if _is_out_of_scope(question):
            logger.info("Node [code_intelligence_agent]: Out of scope question.")
            return build_early_refusal_response(
                OUT_OF_SCOPE_ANSWER, trace_logger, trace_id, question, start_time, state, CI_MAX_HOPS,
            )

        # Security & Massive Extraction Safeguards
        from config.settings import (
            MAX_MODELS_PER_QUERY,
            MASSIVE_EXTRACTION_REFUSAL_MSG,
            PROMPT_INJECTION_REFUSAL_MSG,
        )

        if _is_prompt_injection(question):
            logger.warning("Node [code_intelligence_agent]: Prompt injection attempt intercepted.")
            return build_early_refusal_response(
                PROMPT_INJECTION_REFUSAL_MSG, trace_logger, trace_id, question, start_time, state, CI_MAX_HOPS,
            )

        if _is_massive_extraction_request(question):
            logger.warning("Node [code_intelligence_agent]: Massive extraction request intercepted.")
            return build_early_refusal_response(
                MASSIVE_EXTRACTION_REFUSAL_MSG, trace_logger, trace_id, question, start_time, state, CI_MAX_HOPS,
            )

        # Initialize the knowledge graph and inject into tool wrappers
        G = get_code_intelligence_graph()
        from code_intelligence.agent.tools import ALL_CI_TOOLS
        from code_intelligence.agent.tool_helpers import set_graph_ref, set_llm_ref
        from code_intelligence.rules.security_locks import gate_observation, OmittedItem
        set_graph_ref(G)

        resolved_user_group_xmlids = _resolve_user_group_xmlids(state.get("user_groups", []))
        if state.get("user_groups") and not resolved_user_group_xmlids:
            logger.warning(
                "Node [code_intelligence_agent]: none of the demandeur's %d group ID(s) "
                "resolved to an xml_id -- gating will fail closed for this request.",
                len(state["user_groups"]),
            )

        llm = get_chat_llm(
            temperature=0.0,
            max_retries=0,  # Let _invoke_with_rate_limit handle dynamic header backoff
            max_tokens=1024,
            model_kwargs={"parallel_tool_calls": False},
        )
        set_llm_ref(llm)
        tool_llm_box = [llm.bind_tools(ALL_CI_TOOLS)]

        def _rebuild_tool_llm():
            fresh = get_chat_llm(
                temperature=0.0, max_retries=0, max_tokens=1024,
                model_kwargs={"parallel_tool_calls": False},
            )
            set_llm_ref(fresh)
            tool_llm_box[0] = fresh.bind_tools(ALL_CI_TOOLS)
            return tool_llm_box[0]

        llm_call_count = 0

        # Business Term Resolver -- Map natural language concepts to technical Odoo models/modules
        t_resolver = time.perf_counter()
        concept = resolve_business_term(question, G, llm=llm)
        resolver_time = time.perf_counter() - t_resolver
        if concept.source_step == "llm_arbitration":
            llm_call_count += 1
        concept_resolved_before_rehydration = concept.is_resolved
        from code_intelligence.agent.context_extractors import _rehydrate_sticky_concept
        from core.evidence.evidence_check import check_evidence
        concept = _rehydrate_sticky_concept(concept, state)
        evidence_status = check_evidence(concept, concept_resolved_before_rehydration, state)

        if concept.is_resolved and concept.resolved_modules and not concept.resolved_models and G is not None:
            for mod in concept.resolved_modules:
                mod_node = f"module:{mod}"
                if mod_node in G:
                    for u, v, d in G.in_edges(mod_node, data=True):
                        if u.startswith("model:") and d.get("edge_type") == "DEFINED_IN":
                            m_name = u.split("model:", 1)[1]
                            if m_name not in concept.resolved_models:
                                concept.resolved_models.append(m_name)

        if concept.resolved_models and len(concept.resolved_models) > MAX_MODELS_PER_QUERY:
            concept.resolved_models = _rank_and_cap_resolved_models(
                question, concept.resolved_models, MAX_MODELS_PER_QUERY,
            )

        tool_map = {t.name: t for t in ALL_CI_TOOLS}
        ctx = DispatchContext(
            G=G, concept=concept, question=question, tool_map=tool_map,
            resolved_user_group_xmlids=resolved_user_group_xmlids,
            trace_logger=trace_logger, trace_id=trace_id, hop_cap=CI_MAX_HOPS,
        )
        ctx.llm_call_count = llm_call_count

        system_prompt = CI_SYSTEM_PROMPT + build_business_context_prompt(question, concept, G)

        run_predispatch_chain(ctx)
        system_prompt += ctx.system_prompt_suffix

        if ctx.tool_observations:
            system_prompt += "\n\n[PRIOR TOOL OBSERVATIONS]\n" + "\n---\n".join(ctx.tool_observations)

        final_answer = run_react_loop(
            ctx, system_prompt, chat_history, REACT_RECURSION_LIMIT, tool_llm_box, _rebuild_tool_llm,
        )

        return build_final_response(ctx, final_answer, state, start_time, resolver_time, evidence_status)


def code_intelligence_agent(state: RAGState) -> dict:
    return CodeIntelligenceAgentRunner(state).run()
