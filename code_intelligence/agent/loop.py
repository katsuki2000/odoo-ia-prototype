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
    _truncate_observation_for_budget,
    _tool_call_key,
    PER_TOOL_OBSERVATION_CAPS,
    DEFAULT_OBSERVATION_CAP,
)
from code_intelligence.agent.context_extractors import (
    _extract_amount,
    _extract_company_context,
    _infer_move_type_context,
)
from code_intelligence.agent.can_view_verifier import _format_can_view_amount_fact
from code_intelligence.agent.dispatch_guards import _override_user_groups_arg, UnknownPrincipalError
from code_intelligence.agent.context import DispatchContext

logger = logging.getLogger(__name__)


def execute_tool_calls(ctx: DispatchContext, ai_msg, messages: list) -> None:
    for tool_call in ai_msg.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        tool_id = tool_call["id"]

        if tool_name == "who_has_access_to" and "permission" not in tool_args:
            tool_args["permission"] = "all"

        try:
            tool_args = _override_user_groups_arg(
                tool_name, tool_args, ctx.resolved_user_group_xmlids, ctx.security_principals,
            )
        except UnknownPrincipalError as upe:
            logger.warning("Node [code_intelligence_agent]: %s", upe)
            messages.append(ToolMessage(
                content=f"Appel refuse : {upe}",
                tool_call_id=tool_id,
            ))
            continue

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

                observation_cap = PER_TOOL_OBSERVATION_CAPS.get(
                    tool_name, DEFAULT_OBSERVATION_CAP
                )
                observation = _truncate_observation_for_budget(ctx, observation, observation_cap)

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
                    user_groups=ctx.resolved_user_group_xmlids or [],
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
    _build_dynamic_uncertainty_answer,
    _maybe_build_application_layer_reminder,
)
from code_intelligence.agent.context_extractors import _question_is_inheritance_related
from code_intelligence.rules.structure import (
    _extract_module_extended_models,
    _answer_lacks_extension_coverage,
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
        final_answer = _build_dynamic_uncertainty_answer("\n\n".join(ctx.tool_observations))

    # Section 780 fix: who_has_access_to/evaluate_record_rules are both
    # forced by predispatch (predispatch_access.py) BEFORE this loop is
    # ever entered, so the application-layer reminder's trigger condition
    # (section 779) can already be satisfied here, before the very first
    # tool-selection call -- the in-loop check below (after
    # execute_tool_calls) only catches tools chosen DURING this loop and
    # therefore always arrives one hop too late for the predispatch-only
    # case (confirmed on PUR-Q1). Same guard, checked once more here for
    # the pre-loop state.
    if not final_answer and not ctx.security_distinction_reminder_sent:
        reminder = _maybe_build_application_layer_reminder(
            ctx.question, ctx.tool_observation_tools,
        )
        if reminder:
            messages.append(SystemMessage(content=reminder))
            ctx.security_distinction_reminder_sent = True

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
                ctx.llm_wait += wait
            except Exception as e:
                ctx.llm_call_count += 1  # attempt still counts against the LLM-call budget
                logger.error("LLM tool selection failed: %s", e)
                ai_msg = None

        if ai_msg and getattr(ai_msg, "tool_calls", None):
            messages.append(ai_msg)
            execute_tool_calls(ctx, ai_msg, messages)
            if not ctx.security_distinction_reminder_sent:
                reminder = _maybe_build_application_layer_reminder(
                    ctx.question, ctx.tool_observation_tools,
                )
                if reminder:
                    messages.append(SystemMessage(content=reminder))
                    ctx.security_distinction_reminder_sent = True
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
                synthesis_prompt = build_synthesis_prompt(
                    ctx.question, ctx.tool_observations, ctx.tool_observation_tools,
                    security_principals=ctx.security_principals,
                )
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
                    ctx.llm_wait += synth_wait
                    final_answer = final_resp.content
                    ctx.synthesis_time = time.perf_counter() - t_synth
                    if _detect_any_degenerate_repetition(final_answer):
                        logger.warning(
                            "Node [code_intelligence_agent]: degenerate repetition detected in "
                            "synthesis output (%d chars) -- retrying once with an explicit "
                            "anti-repetition instruction before falling back to stripping it. "
                            "Pre-retry excerpt (first 800 chars, for diagnosis -- see "
                            "todo/contexte.txt section 841): %r",
                            len(final_answer), final_answer[:800],
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
                            ctx.llm_wait += retry_wait
                            if not _detect_any_degenerate_repetition(retry_resp.content):
                                final_answer = retry_resp.content
                            else:
                                logger.error(
                                    "Node [code_intelligence_agent]: synthesis still degenerate "
                                    "after retry -- stripping the repeated run instead of shipping "
                                    "it. Pre-strip retry excerpt (first 800 chars, for diagnosis -- "
                                    "see todo/contexte.txt section 841): %r",
                                    retry_resp.content[:800],
                                )
                                final_answer = _strip_any_degenerate_repetition(final_answer)
                        except Exception as retry_e:
                            logger.error("Anti-repetition retry failed: %s", retry_e)
                            final_answer = _strip_any_degenerate_repetition(final_answer)

                    # todo/contexte.txt section 858 (Option B1, mandated
                    # after the negation-wording whack-a-mole -- 840->841->
                    # 842/843->844->856->857 -- hit diminishing returns 2
                    # recidives in a row): a GENERIC, wording-independent
                    # coverage check (does the answer cite essentially none
                    # of the real extended-model list the tools already
                    # reported?) replaces trying to anticipate one more
                    # negation verb/synonym. Catches denial AND omission
                    # (the STK-Q3 variant, section 821) alike, in one retry,
                    # regardless of exact wording. Mirrors the
                    # anti-repetition retry above: same plain_llm_box, same
                    # _invoke_with_rate_limit, same fail-safe shape --
                    # never raises, never degrades final_answer; if this
                    # retry errors or still doesn't fix it, final_answer is
                    # left untouched for the existing text-patch guard
                    # chain (postprocess.py, sections 838-857) to catch
                    # what it can, unchanged.
                    try:
                        _extended_models = _extract_module_extended_models(
                            "\n\n".join(ctx.tool_observations)
                        )
                        if (
                            _extended_models
                            and _question_is_inheritance_related(ctx.question)
                            and _answer_lacks_extension_coverage(final_answer, _extended_models)
                        ):
                            logger.warning(
                                "Node [code_intelligence_agent]: synthesis reflects "
                                "essentially none of the %d model(s) list_involved_modules "
                                "reported this module extends outside its own perimeter -- "
                                "retrying once with the real list made explicit. Pre-retry "
                                "excerpt (first 800 chars, for diagnosis -- see "
                                "todo/contexte.txt section 858): %r",
                                len(_extended_models), final_answer[:800],
                            )
                            _models_list = ", ".join(f"'{m}'" for m in _extended_models)
                            _coverage_retry_messages = [
                                HumanMessage(content=synthesis_prompt),
                                SystemMessage(content=(
                                    "RAPPEL STRICT : les outils ont confirm\u00e9 que ce "
                                    f"module \u00e9tend bien {len(_extended_models)} "
                                    f"mod\u00e8le(s) en dehors de son propre p\u00e9rim\u00e8tre "
                                    f": {_models_list}. Ta r\u00e9ponse pr\u00e9c\u00e9dente ne "
                                    "refl\u00e9tait pas correctement ce fait (elle le niait "
                                    "ou l'omettait, quelle qu'en soit la formulation). "
                                    "Reformule une r\u00e9ponse compl\u00e8te et coh\u00e9rente "
                                    "qui affirme et cite explicitement cette liste r\u00e9elle, "
                                    "sans aucune phrase qui la contredise ailleurs dans la "
                                    "r\u00e9ponse."
                                )),
                            ]
                            try:
                                _coverage_resp, _coverage_wait = _invoke_with_rate_limit(
                                    plain_llm_box[0], _coverage_retry_messages, max_retries=2,
                                    rebuild_llm=_rebuild_plain_llm,
                                )
                                ctx.llm_call_count += 1  # extension-coverage retry call
                                ctx.llm_wait += _coverage_wait
                                if not _answer_lacks_extension_coverage(
                                    _coverage_resp.content, _extended_models
                                ):
                                    final_answer = _coverage_resp.content
                                else:
                                    logger.error(
                                        "Node [code_intelligence_agent]: synthesis still "
                                        "lacks extension coverage after retry -- leaving "
                                        "final_answer as-is for the existing text-patch "
                                        "guard chain to catch what it can. Post-retry "
                                        "excerpt (first 800 chars): %r",
                                        _coverage_resp.content[:800],
                                    )
                            except Exception as _coverage_e:
                                logger.error("Extension-coverage retry failed: %s", _coverage_e)
                    except Exception as _coverage_outer_e:
                        logger.error("Extension-coverage check failed: %s", _coverage_outer_e)
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
from code_intelligence.agent.prompts import CI_SYSTEM_PROMPT, build_business_context_prompt, build_persona_prompt_block
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
        request_language = state.get("language")
        G = get_code_intelligence_graph(
            translation_languages=[request_language] if request_language else None,
            request_language=request_language,
        )
        from code_intelligence.agent.tools import ALL_CI_TOOLS
        from code_intelligence.agent.tool_helpers import set_graph_ref, set_llm_ref, set_current_question
        from code_intelligence.rules.security_locks import gate_observation, OmittedItem
        set_graph_ref(G)
        # todo/contexte.txt section 846: readable by format_security_locks_summary
        # for intra-block relevance reranking, deep inside a @tool wrapper that
        # has no direct parameter path back to the original question.
        set_current_question(question)

        # Section 888/889: distinguish "state['user_groups'] key absent"
        # (demandeur identity unavailable this turn) from an explicit []
        # (identity known, no groups) -- both still fail closed identically
        # everywhere downstream (every consumer reads `ctx.resolved_user_group_xmlids
        # or []`), the distinction is for correct diagnostics only, see
        # DispatchContext.resolved_user_group_xmlids docstring.
        _USER_GROUPS_UNSET = object()
        _raw_user_groups = state.get("user_groups", _USER_GROUPS_UNSET)
        if _raw_user_groups is _USER_GROUPS_UNSET:
            resolved_user_group_xmlids = None
        else:
            resolved_user_group_xmlids = _resolve_user_group_xmlids(_raw_user_groups)
            if _raw_user_groups and not resolved_user_group_xmlids:
                logger.warning(
                    "Node [code_intelligence_agent]: none of the demandeur's %d group ID(s) "
                    "resolved to an xml_id -- gating will fail closed for this request.",
                    len(_raw_user_groups),
                )

        # Section 888/889: benchmark-only, harness-declared hypothetical
        # security personas (e.g. SAL-Q1's "vendeur" vs "utilisateur portail"),
        # strictly separate from the real demandeur above -- never merged,
        # never used as a fallback for each other. Empty outside benchmark
        # runs that declare state["security_principals"].
        resolved_security_principals = {
            principal_id: _resolve_user_group_xmlids(principal_def.get("group_xmlids", []))
            for principal_id, principal_def in (state.get("security_principals") or {}).items()
        }

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
        concept = resolve_business_term(
            question, G, llm=llm, language=request_language,
        )
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
                        if (
                            u.startswith("model:")
                            and d.get("edge_type") == "DEFINED_IN"
                            and d.get("role", "declares") == "declares"
                        ):
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
            security_principals=resolved_security_principals,
        )
        ctx.llm_call_count = llm_call_count

        system_prompt = CI_SYSTEM_PROMPT + build_business_context_prompt(question, concept, G)

        # Section 888/889 (mecanisme), 899 (texte durci -- SAL-Q1/897 et
        # MNT-Q1/898 rechutaient avec la 1ere version) : tell the LLM which
        # hypothetical personas this question names, and how to evaluate
        # access for each -- via principal_id, never by supplying
        # user_groups_json itself (always ignored/overridden, see
        # dispatch_guards.py::_override_user_groups_arg).
        system_prompt += build_persona_prompt_block(ctx.security_principals)

        run_predispatch_chain(ctx)
        # Section 861 (2a): explicit, always-logged routing decision -- never
        # a silent fallthrough to free ReAct when no predispatch predicate
        # matched (see ReasoningTraceLogger.log_routing docstring).
        trace_logger.log_routing(trace_id, ctx.matched_dispatchers)
        system_prompt += ctx.system_prompt_suffix

        if ctx.tool_observations:
            system_prompt += "\n\n[PRIOR TOOL OBSERVATIONS]\n" + "\n---\n".join(ctx.tool_observations)

        final_answer = run_react_loop(
            ctx, system_prompt, chat_history, REACT_RECURSION_LIMIT, tool_llm_box, _rebuild_tool_llm,
        )

        return build_final_response(ctx, final_answer, state, start_time, resolver_time, evidence_status)


def code_intelligence_agent(state: RAGState) -> dict:
    return CodeIntelligenceAgentRunner(state).run()
