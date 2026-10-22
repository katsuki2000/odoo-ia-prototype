"""Workflow gates, documentary retrieval and final response metadata."""

import logging

from config.settings import USE_RERANKER
from document_rag.vectorstore.search import get_retriever, retrieve as search_retrieve
from core.schemas import AssistantResponse, SourceReference, source_display_title
from core.guardrails import OUT_OF_SCOPE_ANSWER, is_out_of_scope
from core.routing.routing_keywords import _fold_accents, has_explicit_doc_request
from core.state import RAGState

logger = logging.getLogger(__name__)


def out_of_scope_gate(state: RAGState) -> dict:
    if not is_out_of_scope(state.get('question', '')):
        return {}
    return {'response': AssistantResponse(answer=OUT_OF_SCOPE_ANSWER, sources=[], confidence=0.0),
            'route': 'out_of_scope', 'retrieved_chunks': [], 'investigation_plan': None}


def out_of_scope_decision(state: RAGState) -> str:
    return 'format_output' if state.get('response') is not None else 'route'


def _has_explicit_doc_request(state: RAGState) -> bool:
    return has_explicit_doc_request(_fold_accents(state.get('question', '').lower()))


def answered_by_documents(state: RAGState) -> bool:
    return state.get('route') == 'documentaire' or state.get('source_mode') == 'documentation'


def retrieve(state: RAGState) -> dict:
    try:
        chromaManager, bm25Index = get_retriever()
        chunks = search_retrieve(query=state['question'], top_k=10,
            chroma_manager=chromaManager, bm25_index=bm25Index, use_reranker=USE_RERANKER)
    except Exception as error:
        logger.error('Document retrieval failed (%s)', type(error).__name__)
        chunks = []
    return {'retrieved_chunks': chunks}


def format_output(state: RAGState) -> dict:
    response = state.get('response')
    chunks = state.get('retrieved_chunks', [])
    if response:
        response.route = state.get('route')
        response.resolved_concept = state.get('resolved_concept')
        response.evidence_status = state.get('evidence_status')
        response.loop_resolved_concept = state.get('loop_resolved_concept')
        response.investigation_plan = state.get('investigation_plan')
        response.ci_evidence_sufficiency = state.get('ci_evidence_sufficiency')
        response.rag_fallback = False
    if response and chunks and answered_by_documents(state):
        metadata = chunks[0].get('metadata') or {}
        if metadata.get('ocr_quality') == 'low' and metadata.get('type', '') in ('doc_pdf', 'pdf'):
            response.ocr_warning = True
            response.answer += "\n\nAttention : cette information provient d'un document numérisé dont la qualité de lecture est limitée."
        if not response.sources and state.get('sources_fallback_eligible'):
            sources = []
            for chunk in chunks:
                metadata = chunk.get('metadata') or {}
                document = chunk.get('document', '')
                sources.append(SourceReference(source=metadata.get('source', 'unknown'),
                    doc_type=metadata.get('type', 'document'), title=source_display_title(metadata),
                    snippet=document[:100] + '...' if len(document) > 100 else document))
            response.sources = sources
    return {'response': response}


def ci_evidence_decision(state: RAGState) -> str:
    """Legacy caller contract; the active graph selects documentation before CI."""
    if state.get('source_mode') == 'documentation':
        return 'generate'
    if state.get('ci_evidence_sufficiency') and _has_explicit_doc_request(state):
        return 'generate'
    return 'format_output'
