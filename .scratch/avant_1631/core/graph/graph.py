"""LangGraph pipeline with documentation and one Odoo system agent."""

import json
import logging
import os
import sys
import time
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph, START, END

from core.schemas import AssistantResponse, QueryRoute
from core.state import RAGState
from core.routing.routing import route, route_decision
from document_rag.generate_node import generate
from erp_data.orm_agent_node import orm_agent_loop
from core.graph.graph_nodes import out_of_scope_gate, out_of_scope_decision, retrieve, format_output
from core.graph.verify_node import verify_answer
from core.evidence.disclosure import filter_disclosed_evidence
from core.evidence.evidence_collector import start_evidence_collection, collect_and_clear_evidence
import core.graph.graph_compat as _graph_compat
from core.graph.graph_compat import *

logger = logging.getLogger(__name__)


def __getattr__(name: str):
    if hasattr(_graph_compat, name):
        return getattr(_graph_compat, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def build_graph() -> StateGraph:
    workflow = StateGraph(RAGState)
    workflow.add_node('out_of_scope_gate', out_of_scope_gate)
    workflow.add_node('retrieve', retrieve)
    workflow.add_node('route', route)
    workflow.add_node('generate', generate)
    workflow.add_node('orm_agent_loop', orm_agent_loop)
    workflow.add_node('verify_answer', verify_answer)
    workflow.add_node('format_output', format_output)
    workflow.add_edge(START, 'out_of_scope_gate')
    workflow.add_conditional_edges('out_of_scope_gate', out_of_scope_decision, {
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


def query_graph(
    question: str,
    chat_history: Optional[List[BaseMessage]] = None,
    uid: Optional[int] = None,
    api_key: Optional[str] = None,
    skills: Optional[dict] = None,
    user_groups: Optional[List[int | str]] = None,
    user_groups_complete: Optional[bool] = None,
    last_route: Optional[str] = None,
    source_mode: Optional[str] = None,
    language: Optional[str] = None,
    company_id: Optional[int] = None,
    company_ids: Optional[List[int]] = None,
) -> AssistantResponse:
    start_time = time.time()
    if chat_history is None:
        chat_history = []
    if skills is None:
        skills = {}
    from erp_data.odoo_context import (
        odoo_api_key_ctx, odoo_company_id_ctx, odoo_company_ids_ctx, odoo_uid_ctx,
    )
    # Set even missing values so a nested request cannot inherit credentials.
    uid_token = odoo_uid_ctx.set(uid)
    api_key_token = odoo_api_key_ctx.set(api_key)
    company_id_token = odoo_company_id_ctx.set(int(company_id) if company_id is not None else None)
    resolved_company_ids = company_ids
    if resolved_company_ids is None and company_id is not None:
        resolved_company_ids = [int(company_id)]
    company_ids_token = odoo_company_ids_ctx.set(
        [int(x) for x in resolved_company_ids] if resolved_company_ids is not None else None)
    try:
        start_evidence_collection()
        app = build_graph()
        initial_state = {
            'question': question, 'chat_history': chat_history, 'uid': uid, 'skills': skills,
            'timing': {}, 'retrieved_chunks': [], 'raw_answer': '', 'route': None, 'response': None,
            'user_groups': user_groups, 'user_groups_complete': user_groups_complete,
            'last_route': last_route, 'investigation_plan': None,
            'source_mode': source_mode, 'language': language,
        }
        logger.info("Invoking graph for question: '%s'", question)
        final_state = app.invoke(initial_state)
        timing = final_state.get('timing', {})
        timing['total_time'] = time.time() - start_time
        logger.info(json.dumps({'event': 'request_latency', 'metrics': timing}))
        response = final_state['response']
        response.evidence_dossier = filter_disclosed_evidence(
            collect_and_clear_evidence(), final_state.get('sensitive_evidence_allowed', False))
        return response
    except Exception as error:
        logger.error('Graph execution failed: %s', error)
        return AssistantResponse(
            answer="Une erreur interne s'est produite lors de l'exécution du pipeline.",
            sources=[], confidence=0.0)
    finally:
        collect_and_clear_evidence()
        odoo_company_ids_ctx.reset(company_ids_token)
        odoo_company_id_ctx.reset(company_id_token)
        odoo_api_key_ctx.reset(api_key_token)
        odoo_uid_ctx.reset(uid_token)
