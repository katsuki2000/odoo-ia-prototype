"""Workflow gates, documentary retrieval and final response metadata."""

from config.settings import RAG_TOP_K
from document_rag.retrieval.search import get_retriever, retrieve as search_retrieve
from core.schemas import QueryRoute
from core.state import RAGState

_TITLE_BRACKETS = str.maketrans('[]', '()')


def answered_by_documents(state: RAGState) -> bool:
    return state.get('source_mode') == QueryRoute.DOCUMENTARY.value


def retrieve(state: RAGState) -> dict:
    chroma_manager, bm25_index = get_retriever()
    chunks = search_retrieve(query=state['question'], top_k=RAG_TOP_K,
        chroma_manager=chroma_manager, bm25_index=bm25_index)
    return {'retrieved_chunks': chunks}


def sources_line(sources) -> str:
    links = [f"[{s.title.translate(_TITLE_BRACKETS)}]({s.source})"
             for s in sources if s.source.startswith(('http://', 'https://'))]
    return 'Sources: ' + ', '.join(links) if links else ''


def format_output(state: RAGState) -> dict:
    response = state.get('response')
    chunks = state.get('retrieved_chunks', [])
    if response:
        response.route = state.get('source_mode')
        if line := sources_line(response.sources):
            response.answer += '\n\n' + line
    if response and chunks and answered_by_documents(state):
        metadata = chunks[0].get('metadata') or {}
        if metadata.get('ocr_quality') == 'low' and metadata.get('type', '') in ('doc_pdf', 'pdf'):
            response.ocr_warning = True
    return {'response': response}
