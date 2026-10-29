"""LangGraph pipeline with documentation and one Odoo system agent."""

import json
import logging
import time
from functools import cache
from typing import List, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph, START, END

from core.schemas import AssistantResponse, QueryRoute
from core.state import RAGState
from core.routing.routing import route, route_decision
from document_rag.generate_node import generate
from erp_data.orm_agent_node import orm_agent_loop
from core.graph.graph_nodes import guard_gate, guard_decision, retrieve, format_output
from core.graph.verify_node import verify_answer
from core.evidence.disclosure import filter_disclosed_evidence
from core.evidence.evidence_collector import start_evidence_collection, collect_and_clear_evidence
from erp_data.odoo_context import request_identity

logger = logging.getLogger(__name__)


def build_graph() -> StateGraph:
    workflow = StateGraph(RAGState)
    workflow.add_node('guard_gate', guard_gate)
    workflow.add_node('retrieve', retrieve)
    workflow.add_node('route', route)
    workflow.add_node('generate', generate)
    workflow.add_node('orm_agent_loop', orm_agent_loop)
    workflow.add_node('verify_answer', verify_answer)
    workflow.add_node('format_output', format_output)
    workflow.add_edge(START, 'guard_gate')
    workflow.add_conditional_edges('guard_gate', guard_decision, {
        'format_output': 'format_output', 'route': 'route',
    })
    workflow.add_conditional_edges('route', route_decision, {
        'source_clarification': 'format_output',
        QueryRoute.DOCUMENTARY.value: 'retrieve',
        QueryRoute.ERP_DATA.value: 'orm_agent_loop',
    })
    workflow.add_edge('retrieve', 'generate')
    workflow.add_edge('generate', 'verify_answer')
    workflow.add_edge('orm_agent_loop', 'verify_answer')
    workflow.add_edge('verify_answer', 'format_output')
    workflow.add_edge('format_output', END)
    return workflow.compile()


@cache
def _compiled_graph():
    return build_graph()


def query_graph(
    question: str,
    chat_history: Optional[List[BaseMessage]] = None,
    uid: Optional[int] = None,
    api_key: Optional[str] = None,
    last_route: Optional[str] = None,
    source_mode: Optional[str] = None,
    language: Optional[str] = None,
    company_id: Optional[int] = None,
    company_ids: Optional[List[int]] = None,
    db: Optional[str] = None,
) -> AssistantResponse:
    start_time = time.time()
    initial_state = {
        'question': question, 'chat_history': chat_history or [], 'uid': uid,
        'timing': {}, 'retrieved_chunks': [], 'route': None, 'response': None,
        'last_route': last_route,
        'source_mode': source_mode, 'language': language,
    }
    with request_identity(uid, api_key, company_id, company_ids, db):
        start_evidence_collection()
        try:
            logger.info("Invoking graph for question: '%s'", question)
            final_state = _compiled_graph().invoke(initial_state)
            timing = final_state.get('timing', {})
            timing['total_time'] = time.time() - start_time
            logger.info(json.dumps({'event': 'request_latency', 'metrics': timing}))
            response = final_state['response']
            response.evidence_dossier = filter_disclosed_evidence(collect_and_clear_evidence())
            return response
        finally:
            collect_and_clear_evidence()
