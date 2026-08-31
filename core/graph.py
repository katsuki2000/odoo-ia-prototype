"""
core/graph.py

LangGraph RAG pipeline with hybrid routing.
Flow:
  smalltalk_gate → out_of_scope_gate → retrieve → route → [documentaire]        → generate               → format_output → END
                                                         → [donnees_erp]         → orm_agent_loop         → format_output → END
                                                         → [hybride]             → hybrid_node            → format_output → END
                                                         → [code_intelligence]   → code_intelligence_agent → format_output → END
"""

import json
import logging
import os
import sys
import time
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from code_intelligence.business_resolver import ResolvedConcept

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_groq import ChatGroq
from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph, START, END

from config.settings import USE_RERANKER
from document_rag.vectorstore.search import get_retriever, retrieve as search_retrieve
from core.smalltalk import classify_smalltalk, SMALLTALK_RESPONSES

# ── Backward-compatible re-exports from schemas ──────────────────────────────
from core.schemas import (
    AssistantResponse,
    SourceReference,
    LLMResponse,
    QueryRoute,
    source_display_title,
)

# ── Backward-compatible re-exports from llm_client ────────────────────────────
from core.llm_client import (
    get_chat_llm,
    invoke_with_rate_limit as _invoke_with_rate_limit,
    _parse_reset_seconds,
    _extract_rate_limit_headers,
    _ToolCallFallback,
    _try_recover_tool_use_failed,
    _reduce_message_context,
    _TOOL_MSG_HARD_CAP,
    _TOOL_USE_FAILED_RE,
    _FAILED_GEN_CALL_RE,
    _llm_call_lock as _groq_call_lock,
    _last_llm_call_time as _last_groq_call_time,
    MIN_LLM_CALL_INTERVAL as MIN_GROQ_CALL_INTERVAL,
)

# ── Backward-compatible re-exports from degenerate_guards ─────────────────────
from core.degenerate_guards import (
    _DEGENERATE_REPETITION_RE,
    _DEGENERATE_LINE_REPETITION_MIN_REPEATS,
    _DEGENERATE_LINE_MIN_LENGTH,
    _DEGENERATE_BLANK_RUN_RE,
    _DEGENERATE_PREFIX_LENGTH,
    _DEGENERATE_PREFIX_MIN_REPEATS,
    _detect_degenerate_repetition,
    _strip_degenerate_repetition,
    _detect_degenerate_line_repetition,
    _strip_degenerate_line_repetition,
    _detect_degenerate_blank_run,
    _strip_degenerate_blank_run,
    _detect_degenerate_growing_repetition,
    _strip_degenerate_growing_repetition,
    _detect_any_degenerate_repetition,
    _strip_any_degenerate_repetition,
)

# ── Backward-compatible re-exports from routing ───────────────────────────────
from core.routing import (
    RAGState,
    ERP_TYPES,
    ROUTING_CONFLICT_PRIORITY,
    ERP_KEYWORDS,
    ERP_KEYWORDS_FOLDED,
    CODE_INTEL_KEYWORDS,
    CODE_INTEL_KEYWORDS_FOLDED,
    QUANTITATIVE_TERMS,
    QUANTITATIVE_TERMS_FOLDED,
    DOC_KEYWORDS,
    DOC_KEYWORDS_FOLDED,
    DATA_TERMS,
    DATA_TERMS_FOLDED,
    DOC_ANCHORS,
    DOC_ANCHORS_FOLDED,
    THRESHOLD_QUERY_TERMS,
    THRESHOLD_QUERY_TERMS_FOLDED,
    _fold_accents,
    _fold_keywords,
    OUT_OF_SCOPE_ANSWER,
    OUT_OF_SCOPE_TERMS,
    REACT_RECURSION_LIMIT,
    _is_out_of_scope,
    _MASSIVE_EXTRACTION_PATTERNS,
    _PROMPT_INJECTION_PATTERNS,
    _is_massive_extraction_request,
    _is_prompt_injection,
    _VALID_ROUTES,
    _sticky_route_or_default,
    route,
    route_decision,
)

# ── Backward-compatible re-exports from generate_node ─────────────────────────
from document_rag.generate_node import (
    _parse_raw_json_answer,
    generate,
)

# ── Backward-compatible re-exports from orm_agent_node ────────────────────────
from erp_data.orm_agent_node import (
    orm_agent_loop,
    hybrid_node,
)

# ── Backward-compatible re-exports from ci_graph_loader ───────────────────────
from code_intelligence.ci_graph_loader import (
    _CACHED_CODE_INTEL_GRAPH,
    _CACHED_GRAPH_MTIME,
    GRAPH_JSON_PATH,
    _load_module,
    get_code_intelligence_graph,
)

# ── Backward-compatible re-exports from ci_helpers ────────────────────────────
from code_intelligence.ci_helpers import (
    CI_SYSTEM_PROMPT,
    CI_MAX_HOPS,
    _AMOUNT_PATTERN,
    _APPROVAL_PATTERN,
    _AUTOMATION_PATTERN,
    _question_mentions_amount,
    _extract_amount,
    _COMPANY_DIFFERENT_PATTERN,
    _COMPANY_SAME_PATTERN,
    _extract_company_context,
    _MOVE_TYPE_ALIAS_MAP,
    _infer_move_type_context,
    _question_is_approval_related,
    _ACCESS_QUESTION_PATTERN,
    _question_is_access_related,
    _REQUIRED_GROUP_LINE_RE,
    _GROUP_XMLID_RE,
    _extract_required_groups,
    _flag_ungrounded_group_xmlids,
    _grounded_core_only_groups,
    _strip_core_only_group_mentions,
    _scoped_raw_tool_output,
    _LOCK_CONDITION_LINE_RE,
    _AMOUNT_CMP_RE,
    _extract_required_groups_for_amount,
    _BLOCK_FILE_LINK_RE,
    _block_is_custom_module_file,
    _restrict_blocks_to_custom_modules,
    _backfill_missing_required_groups,
    _OVERRIDE_CHAIN_AMOUNT_RE,
    _amount_present_in_text,
    _SECURITY_LOCK_MESSAGES_MARKER,
    _extract_security_lock_condition_amounts,
    _backfill_missing_security_lock_amount,
    _LINK_GUARD_RE,
    _LINK_GUARD_CONTRADICTION_PATTERN,
    _LINK_GUARD_CONTRADICTING_SENTENCE_RE,
    _answer_contradicts_link_guard,
    _neutralize_contradicting_link_guard_sentence,
    _extract_link_guard_fields,
    _TRIGGER_CONDITION_RE,
    _TRIGGER_CONDITION_LITERAL_RE,
    _extract_trigger_condition_literals,
    _backfill_missing_trigger_condition_literals,
    _HARDCODED_IDS_LINE_RE,
    _extract_hardcoded_id_literals,
    _backfill_missing_hardcoded_id_literals,
    _backfill_link_guard_clarifications,
    _CAN_VIEW_ALLOW_ASSERTION_RE,
    _CAN_VIEW_DENY_ASSERTION_RE,
    _CAN_VIEW_FACT_VERDICT_RE,
    _CAN_VIEW_FACT_INDETERMINATE_MARKER,
    _split_before_first_fact_marker,
    _extract_can_view_amount_verdict,
    _has_can_view_amount_fact,
    _correct_can_view_amount_contradictions,
    _correct_security_lock_threshold_contradictions,
    _extract_can_view_amount_fact_block,
    _backfill_missing_can_view_amount_fact,
    _format_can_view_amount_fact,
    _question_suggests_automation_bypass,
    _rank_and_cap_resolved_models,
    _override_user_groups_arg,
    _COULD_NOT_RESOLVE_RE,
    _strip_group_resolution_noise,
    _extract_first_scoped_file_link,
    _TECHNICAL_MODEL_LOOKALIKE_RE,
    _force_out_of_scope_model_answer,
    _force_dynamic_uncertainty_answer,
)

from code_intelligence.ci_override_cascade import (
    _OVERRIDE_MODULE_RE,
    _extract_override_modules,
    _word_boundary_present,
    _backfill_missing_override_modules,
    _extract_override_chain_amounts,
    _backfill_missing_override_chain_amount,
    _correct_override_cascade_contradictions,
    _OVERRIDE_COUNT_DENIAL_RE,
    _OVERRIDE_ORDER_SHORTCIRCUIT_SENTENCE_RE,
    _answer_denies_other_overrides,
    _answer_asserts_override_shortcircuit,
    _neutralize_override_count_denial,
    _neutralize_override_shortcircuit_sentence,
    _UNGUARDED_SUPER_RE,
    _extract_unguarded_super_findings,
    _backfill_missing_unguarded_super,
    _MAX_OVERRIDE_CASCADE_DISPATCH,
    _rank_and_cap_override_methods,
)

# ── Backward-compatible re-exports from ci_agent_node ─────────────────────────
from code_intelligence.ci_agent_node import (
    _GROUP_XMLID_CACHE,
    _ADMIN_RPC_CLIENT,
    _ADMIN_RPC_UID,
    _get_admin_rpc_client,
    _resolve_user_group_xmlids,
    code_intelligence_agent,
)

logger = logging.getLogger(__name__)


# ── Pipeline Nodes ────────────────────────────────────────────────────────────

def smalltalk_gate(state: RAGState) -> dict:
    """
    Deterministic pre-retrieval gate for pure smalltalk (greetings,
    thanks, farewells) -- todo/contexte.txt section 294. No GREETING
    route exists in QueryRoute, so an unclassified question used to fall
    through to the DOCUMENTAIRE default and still run retrieve() first
    (retrieve() is unconditional, before route() even runs) -- this node
    intercepts pure smalltalk BEFORE retrieve() so it never happens for
    these questions. Never rewrites `question` -- only classify_smalltalk()
    is consulted, downstream nodes still see the original question.
    """
    question = state.get("question", "")
    kind = classify_smalltalk(question)
    if kind is None:
        return {}

    logger.info("Node [smalltalk_gate]: pure smalltalk detected (%s) -- skipping retrieve()/route()", kind)
    response = AssistantResponse(
        answer=SMALLTALK_RESPONSES[kind],
        sources=[],
        confidence=1.0,
    )
    return {"response": response, "route": "smalltalk", "retrieved_chunks": [], "investigation_plan": None}


def smalltalk_decision(state: RAGState) -> str:
    """Return the conditional-edge key out of smalltalk_gate."""
    return "format_output" if state.get("response") is not None else "out_of_scope_gate"


def out_of_scope_gate(state: RAGState) -> dict:
    """
    Deterministic pre-retrieval gate for questions matching OUT_OF_SCOPE_TERMS
    (todo/contexte.txt sections 360-361). generate()'s own _is_out_of_scope
    fast-fail only ran after retrieve()/route() had already executed for
    every out-of-scope question, paying for a retrieval call it never used --
    the same waste smalltalk_gate already closed for pure smalltalk. This
    node intercepts them before retrieve() runs, same pattern as
    smalltalk_gate. generate()'s own check is left in place as a
    defense-in-depth safety net.
    """
    question = state.get("question", "")
    if not _is_out_of_scope(question):
        return {}

    logger.info("Node [out_of_scope_gate]: out-of-scope question detected -- skipping retrieve()/route()")
    response = AssistantResponse(
        answer=OUT_OF_SCOPE_ANSWER,
        sources=[],
        confidence=0.0,
    )
    return {"response": response, "route": "out_of_scope", "retrieved_chunks": [], "investigation_plan": None}


def out_of_scope_decision(state: RAGState) -> str:
    """Return the conditional-edge key out of out_of_scope_gate."""
    return "format_output" if state.get("response") is not None else "retrieve"


def retrieve(state: RAGState) -> dict:
    """Retrieve relevant documents for the query."""
    import time
    start_time = time.time()
    question = state["question"]
    logger.info("Node [retrieve]: Fetching documents for: %s", question)
    
    try:
        chroma_manager, bm25_index = get_retriever()
        chunks = search_retrieve(
            query=question, 
            top_k=10, 
            chroma_manager=chroma_manager,
            bm25_index=bm25_index,
            use_reranker=USE_RERANKER
        )
    except Exception as e:
        logger.error("Error during retrieval: %s", e)
        chunks = []
        
    return {"retrieved_chunks": chunks}


def format_output(state: RAGState) -> dict:
    """Format and clean up the final output (e.g. OCR warnings)."""
    logger.info("Node [format_output]: Formatting final response")
    
    response = state.get("response")
    chunks = state.get("retrieved_chunks", [])
    route = state.get("route")

    if response:
        response.route = route
        response.resolved_concept = state.get("resolved_concept")
        response.evidence_status = state.get("evidence_status")
        response.investigation_plan = state.get("investigation_plan")

    if response and chunks and route == QueryRoute.DOCUMENTAIRE.value:
        primary_chunk = chunks[0]
        primary_metadata = primary_chunk.get("metadata") or {}
        primary_type = primary_metadata.get("type", "")
        has_low_ocr = (
            primary_metadata.get("ocr_quality") == "low"
            and primary_type in ("doc_pdf", "pdf")
        )
        if has_low_ocr:
            response.ocr_warning = True
            response.answer += "\n\n *Cette information provient d'un document numérisé dont la qualité de lecture est limitée.*"

        # Populate sources from chunks if not already set (documentary branch)
        if not response.sources:
            sources = []
            for chunk in chunks:
                meta = chunk.get("metadata") or {}
                doc = chunk.get("document", "")
                snippet = doc[:100] + "..." if len(doc) > 100 else doc
                
                sources.append(SourceReference(
                    source=meta.get("source", "unknown"),
                    doc_type=meta.get("type", "document"),
                    title=source_display_title(meta),
                    snippet=snippet
                ))
            response.sources = sources
            
        if response.sources and "[Source:" not in response.answer:
            main_src = response.sources[0].title or response.sources[0].source
            response.answer += f"\n\n[Source: Documentation ERP - {main_src}]"

    return {"response": response}


# ── Graph Construction ────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    """Build and compile the RAG LangGraph with hybrid routing."""
    workflow = StateGraph(RAGState)

    # Add nodes
    workflow.add_node("smalltalk_gate", smalltalk_gate)
    workflow.add_node("out_of_scope_gate", out_of_scope_gate)
    workflow.add_node("retrieve", retrieve)
    workflow.add_node("route", route)
    workflow.add_node("generate", generate)
    workflow.add_node("orm_agent_loop", orm_agent_loop)
    workflow.add_node("hybrid_node", hybrid_node)
    workflow.add_node("code_intelligence_agent", code_intelligence_agent)
    workflow.add_node("format_output", format_output)

    # Edges
    workflow.add_edge(START, "smalltalk_gate")
    workflow.add_conditional_edges("smalltalk_gate", smalltalk_decision, {
        "format_output": "format_output",
        "out_of_scope_gate": "out_of_scope_gate",
    })
    workflow.add_conditional_edges("out_of_scope_gate", out_of_scope_decision, {
        "format_output": "format_output",
        "retrieve": "retrieve",
    })
    workflow.add_edge("retrieve", "route")

    # Conditional routing
    workflow.add_conditional_edges("route", route_decision, {
        QueryRoute.DOCUMENTAIRE.value: "generate",
        QueryRoute.DONNEES_ERP.value: "orm_agent_loop",
        QueryRoute.HYBRIDE.value: "hybrid_node",
        QueryRoute.CODE_INTELLIGENCE.value: "code_intelligence_agent",
    })

    workflow.add_edge("generate", "format_output")
    workflow.add_edge("orm_agent_loop", "format_output")
    workflow.add_edge("hybrid_node", "format_output")
    workflow.add_edge("code_intelligence_agent", "format_output")
    workflow.add_edge("format_output", END)

    return workflow.compile()


def query_graph(
    question: str,
    chat_history: Optional[List[BaseMessage]] = None,
    uid: Optional[int] = None,
    api_key: Optional[str] = None,
    skills: Optional[dict] = None,
    user_groups: Optional[List[int]] = None,
    last_route: Optional[str] = None,
    last_resolved_concept: Optional[dict] = None,
) -> AssistantResponse:
    import time
    import json
    start_time = time.time()
    
    if chat_history is None:
        chat_history = []
    if skills is None:
        skills = {}

    from erp_data.odoo_tools import odoo_uid_ctx, odoo_api_key_ctx
    # Propagate the uid and api_key to tools via contextvars
    uid_token = None
    api_key_token = None
    if uid is not None:
        uid_token = odoo_uid_ctx.set(uid)
    if api_key is not None:
        api_key_token = odoo_api_key_ctx.set(api_key)

    try:
        app = build_graph()
        initial_state = {
            "question": question,
            "chat_history": chat_history,
            "uid": uid,
            "skills": skills,
            "timing": {},
            "retrieved_chunks": [],
            "raw_answer": "",
            "route": None,
            "response": None,
            "user_groups": user_groups or [],
            "last_route": last_route,
            "last_resolved_concept": last_resolved_concept,
            "investigation_plan": None,
        }
    
        logger.info("Invoking graph for question: '%s'", question)
        final_state = app.invoke(initial_state)
        
        # Logging structured latency
        timing = final_state.get("timing", {})
        timing["total_time"] = time.time() - start_time
        logger.info(json.dumps({"event": "request_latency", "metrics": timing}))
        
        return final_state["response"]
    except Exception as e:
        logger.error("Graph execution failed: %s", e)
        return AssistantResponse(
            answer="Une erreur interne s'est produite lors de l'exécution du pipeline.",
            sources=[],
            confidence=0.0
        )
    finally:
        if uid_token:
            odoo_uid_ctx.reset(uid_token)
        if api_key_token:
            odoo_api_key_ctx.reset(api_key_token)
