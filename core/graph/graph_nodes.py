"""Workflow gates, documentary retrieval and final response metadata."""

from config.settings import RAG_TOP_K
from document_rag.vectorstore.search import get_retriever, retrieve as search_retrieve
from core.schemas import AssistantResponse, SourceReference, source_display_title
from core.guardrails import refusal_message
from core.state import RAGState


def guard_gate(state: RAGState) -> dict:
    refusal = refusal_message(state.get('question', ''))
    if refusal is None:
        return {}
    return {'response': AssistantResponse(answer=refusal, sources=[], confidence=0.0),
            'route': 'out_of_scope', 'retrieved_chunks': []}


def guard_decision(state: RAGState) -> str:
    return 'format_output' if state.get('response') is not None else 'route'


def answered_by_documents(state: RAGState) -> bool:
    return state.get('route') == 'documentaire' or state.get('source_mode') == 'documentation'


def retrieve(state: RAGState) -> dict:
    chroma_manager, bm25_index = get_retriever()
    chunks = search_retrieve(query=state['question'], top_k=RAG_TOP_K,
        chroma_manager=chroma_manager, bm25_index=bm25_index)
    return {'retrieved_chunks': chunks}


def format_output(state: RAGState) -> dict:
    response = state.get('response')
    chunks = state.get('retrieved_chunks', [])
    if response:
        response.route = state.get('route')
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
