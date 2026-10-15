"""
core/graph.py

LangGraph pipeline with a source choice: documentation or Odoo system.
Orchestrates StateGraph compilation, node dispatch, and pipeline querying.
"""

import json
import logging
import os
import sys
import time
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from code_intelligence.agent.matching import ResolvedConcept

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph, START, END

from core.schemas import AssistantResponse, QueryRoute
from core.state import RAGState
from core.routing.routing import route, route_decision
from document_rag.generate_node import generate
# Not used directly below -- kept as monkeypatch targets for graph_nodes.py::retrieve(),
# which resolves these two names off this module first (sys.modules lookup) before
# falling back to its own import, so tests can patch "core.graph.graph.get_retriever".
from document_rag.vectorstore.search import get_retriever, retrieve as search_retrieve
from erp_data.orm_agent_node import orm_agent_loop
from code_intelligence.agent.loop import code_intelligence_agent

from core.graph.graph_nodes import (
    out_of_scope_gate,
    out_of_scope_decision,
    retrieve,
    format_output,
)
from core.graph.verify_node import verify_answer
from core.evidence.evidence_collector import start_evidence_collection, collect_and_clear_evidence

# Backward-compatible re-exports for legacy callers and tests
import core.graph.graph_compat as _graph_compat
from core.graph.graph_compat import *

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

    workflow.add_node("out_of_scope_gate", out_of_scope_gate)
    workflow.add_node("retrieve", retrieve)
    workflow.add_node("route", route)
    workflow.add_node("generate", generate)
    workflow.add_node("orm_agent_loop", orm_agent_loop)
    workflow.add_node("code_intelligence_agent", code_intelligence_agent)
    workflow.add_node("verify_answer", verify_answer)
    workflow.add_node("format_output", format_output)

    # Decide the source before doing retrieval or invoking an agent.
    workflow.add_edge(START, "out_of_scope_gate")
    workflow.add_conditional_edges("out_of_scope_gate", out_of_scope_decision, {
        "format_output": "format_output",
        "route": "route",
    })

    workflow.add_conditional_edges("route", route_decision, {
        QueryRoute.DOCUMENTAIRE.value: "retrieve",
        QueryRoute.DONNEES_ERP.value: "orm_agent_loop",
        QueryRoute.HYBRIDE.value: "code_intelligence_agent",
        QueryRoute.CODE_INTELLIGENCE.value: "code_intelligence_agent",
    })

    workflow.add_edge("retrieve", "generate")
    workflow.add_edge("generate", "verify_answer")
    workflow.add_edge("code_intelligence_agent", "verify_answer")
    workflow.add_edge("orm_agent_loop", "verify_answer")
    workflow.add_edge("verify_answer", "format_output")
    workflow.add_edge("format_output", END)

    return workflow.compile()


def query_graph(
    question: str,
    chat_history: Optional[List[BaseMessage]] = None,
    uid: Optional[int] = None,
    api_key: Optional[str] = None,
    skills: Optional[dict] = None,
    user_groups: Optional[List[int | str]] = None,
    user_groups_complete: Optional[bool] = None,
    last_route: Optional[str] = None,
    last_resolved_concept: Optional[dict] = None,
    source_mode: Optional[str] = None,
    language: Optional[str] = None,
    company_id: Optional[int] = None,
    company_ids: Optional[List[int]] = None,
) -> AssistantResponse:
    """Execute the compiled graph with the provided question and context."""
    start_time = time.time()

    if chat_history is None:
        chat_history = []
    if skills is None:
        skills = {}

    from erp_data.odoo_context import (
        odoo_api_key_ctx,
        odoo_company_id_ctx,
        odoo_company_ids_ctx,
        odoo_uid_ctx,
    )
    uid_token = None
    api_key_token = None
    company_id_token = None
    company_ids_token = None
    if uid is not None:
        uid_token = odoo_uid_ctx.set(uid)
    if api_key is not None:
        api_key_token = odoo_api_key_ctx.set(api_key)
    if company_id is not None:
        company_id_token = odoo_company_id_ctx.set(int(company_id))
    resolved_company_ids = company_ids
    if resolved_company_ids is None and company_id is not None:
        resolved_company_ids = [int(company_id)]
    if resolved_company_ids is not None:
        company_ids_token = odoo_company_ids_ctx.set([int(x) for x in resolved_company_ids])

    try:
        start_evidence_collection()
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
            "user_groups_complete": user_groups_complete,
            "last_route": last_route,
            "last_resolved_concept": last_resolved_concept,
            "investigation_plan": None,
            "source_mode": source_mode,
            "language": language,
        }

        logger.info("Invoking graph for question: '%s'", question)
        final_state = app.invoke(initial_state)

        timing = final_state.get("timing", {})
        timing["total_time"] = time.time() - start_time
        logger.info(json.dumps({"event": "request_latency", "metrics": timing}))

        response = final_state["response"]
        response.evidence_dossier = collect_and_clear_evidence()
        return response
    except Exception as e:
        logger.error("Graph execution failed: %s", e)
        return AssistantResponse(
            answer="Une erreur interne s'est produite lors de l'exécution du pipeline.",
            sources=[],
            confidence=0.0,
        )
    finally:
        # Safety net: drains any partial accumulator left by an exception
        # path above so it never leaks into the next request on this same
        # thread/context -- no-op (returns []) if already collected above.
        collect_and_clear_evidence()
        if uid_token:
            odoo_uid_ctx.reset(uid_token)
        if api_key_token:
            odoo_api_key_ctx.reset(api_key_token)
        if company_id_token:
            odoo_company_id_ctx.reset(company_id_token)
        if company_ids_token:
            odoo_company_ids_ctx.reset(company_ids_token)
