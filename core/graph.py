"""
core/graph.py

LangGraph RAG pipeline -- CI-first, RAG-as-last-resort.
Orchestrates StateGraph compilation, node dispatch, and pipeline querying.
"""

import json
import logging
import os
import sys
import time
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from code_intelligence.business_resolver import ResolvedConcept

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_groq import ChatGroq
from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph, START, END

from document_rag.vectorstore.search import get_retriever, retrieve as search_retrieve
from core.schemas import AssistantResponse, QueryRoute
from core.routing import RAGState, route, route_decision
from document_rag.generate_node import generate
from erp_data.orm_agent_node import orm_agent_loop
from code_intelligence.ci_agent_node import code_intelligence_agent

from core.graph_nodes import (
    smalltalk_gate,
    smalltalk_decision,
    out_of_scope_gate,
    out_of_scope_decision,
    retrieve,
    format_output,
    ci_evidence_decision,
)

# Backward-compatible re-exports for legacy callers and tests
import core.graph_compat as _graph_compat
from core.graph_compat import *

logger = logging.getLogger(__name__)


def __getattr__(name: str):
    """Dynamic fallback for backward-compatible re-exports from graph_compat."""
    if hasattr(_graph_compat, name):
        return getattr(_graph_compat, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


# ── Graph Construction ────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    """Build and compile the RAG LangGraph -- CI-first, RAG-as-last-resort."""
    workflow = StateGraph(RAGState)

    workflow.add_node("smalltalk_gate", smalltalk_gate)
    workflow.add_node("out_of_scope_gate", out_of_scope_gate)
    workflow.add_node("retrieve", retrieve)
    workflow.add_node("route", route)
    workflow.add_node("generate", generate)
    workflow.add_node("orm_agent_loop", orm_agent_loop)
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

    # Conditional routing -- CI-first
    workflow.add_conditional_edges("route", route_decision, {
        QueryRoute.DOCUMENTAIRE.value: "code_intelligence_agent",
        QueryRoute.DONNEES_ERP.value: "orm_agent_loop",
        QueryRoute.HYBRIDE.value: "code_intelligence_agent",
        QueryRoute.CODE_INTELLIGENCE.value: "code_intelligence_agent",
    })

    # Post-CI: SUFFICIENT and CONFLICTING stay on CI's answer; INSUFFICIENT falls back to RAG
    workflow.add_conditional_edges("code_intelligence_agent", ci_evidence_decision, {
        "format_output": "format_output",
        "generate": "generate",
    })

    workflow.add_edge("generate", "format_output")
    workflow.add_edge("orm_agent_loop", "format_output")
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
    active_model: Optional[str] = None,
    active_id: Optional[int] = None,
) -> AssistantResponse:
    """Execute the compiled graph with the provided question and context."""
    start_time = time.time()

    if chat_history is None:
        chat_history = []
    if skills is None:
        skills = {}

    from erp_data._odoo_helpers import odoo_uid_ctx, odoo_api_key_ctx
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
            "active_model": active_model,
            "active_id": active_id,
        }

        logger.info("Invoking graph for question: '%s'", question)
        final_state = app.invoke(initial_state)

        timing = final_state.get("timing", {})
        timing["total_time"] = time.time() - start_time
        logger.info(json.dumps({"event": "request_latency", "metrics": timing}))

        return final_state["response"]
    except Exception as e:
        logger.error("Graph execution failed: %s", e)
        return AssistantResponse(
            answer="Une erreur interne s'est produite lors de l'exécution du pipeline.",
            sources=[],
            confidence=0.0,
        )
    finally:
        if uid_token:
            odoo_uid_ctx.reset(uid_token)
        if api_key_token:
            odoo_api_key_ctx.reset(api_key_token)
