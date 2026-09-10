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
from code_intelligence.knowledge_rules.graph import get_code_intelligence_graph
from code_intelligence.agent.business_resolver import resolve_business_term
from code_intelligence.agent.ci_agent_node.context.prompt_and_heuristics import CI_MAX_HOPS
from code_intelligence.agent.ci_agent_node.guards.dispatch_utils import _rank_and_cap_resolved_models
from code_intelligence.agent.ci_agent_node.context.group_resolution import _resolve_user_group_xmlids
from code_intelligence.agent.ci_agent_node.context.early_refusal import build_early_refusal_response
from code_intelligence.agent.ci_agent_node.context.dispatch_context import DispatchContext
from code_intelligence.agent.ci_agent_node.context.prompts import CI_SYSTEM_PROMPT, build_business_context_prompt
from code_intelligence.agent.ci_agent_node.predispatch.predispatch_chain import run_predispatch_chain
from .react_loop import run_react_loop
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
        from code_intelligence.agent.ci_agent_node.tools import ALL_CI_TOOLS
        from code_intelligence.agent.ci_agent_node.context.tool_helpers import set_graph_ref, set_llm_ref
        from code_intelligence.knowledge_rules.security.gate import gate_observation, OmittedItem
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
        from code_intelligence.agent.ci_agent_node.context.context_extractors import _rehydrate_sticky_concept
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
