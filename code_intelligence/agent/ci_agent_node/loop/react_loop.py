"""
code_intelligence/ci_agent_node/react_loop.py

The CI agent's single-pass composite ReAct loop (tool-selection turn +
tool execution + synthesis turn), plus the degenerate-repetition retry on
the synthesized answer. Extracted from the former ci_agent_node.py
monolith (refactor, see todo/contexte.txt). Behavior unchanged.
"""

import logging
import time

from langchain_core.messages import SystemMessage, HumanMessage

from code_intelligence.agent.ci_agent_node.guards.dispatch_utils import (
    _strip_group_resolution_noise,
    _force_dynamic_uncertainty_answer,
)
from core.llm_client import get_chat_llm, invoke_with_rate_limit as _invoke_with_rate_limit
from core.degenerate_guards import (
    _detect_any_degenerate_repetition,
    _strip_any_degenerate_repetition,
)
from code_intelligence.agent.ci_agent_node.context.dispatch_context import DispatchContext
from code_intelligence.agent.ci_agent_node.context.prompts import build_synthesis_prompt
from .tool_call_execution import execute_tool_calls

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
        # J251 fix (todo/contexte.txt section 250-251): the deterministic
        # pre-dispatch blocks each break their OWN loop once hop_count
        # reaches the cap, but nothing previously stopped THIS ReAct loop
        # from still invoking llm_with_tools for at least one more
        # iteration when the hop budget was already exhausted by
        # pre-dispatch. Skipping the tool-selection call outright once the
        # budget is already spent closes the gap at its root: no second
        # call is ever issued, nothing to reconcile after the fact.
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
                # Q6.1 fix: strip 'could not be resolved' noise from
                # who_has_access_to before it reaches the synthesis LLM when
                # the real-auth override has already injected the
                # demandeur's real groups into evaluate_record_rules and a
                # deterministic can_view_amount fact is present.
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
                final_answer = "Je n'ai pas de données disponibles dans le graphe de connaissances pour répondre à cette question."

        if final_answer:
            break

    return final_answer
