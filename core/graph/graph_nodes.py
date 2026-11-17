"""Workflow gates, documentary retrieval and final response metadata."""

from config.settings import RAG_TOP_K
from document_rag.retrieval.search import quick_retrieve
from core.schemas import QueryRoute
from core.state import RAGState

_TITLE_BRACKETS = str.maketrans('[]', '()')


def answered_by_documents(state: RAGState) -> bool:
    return state.get('source_mode') == QueryRoute.DOCUMENTARY.value


def retrieve(state: RAGState) -> dict:
    return {'retrieved_chunks': quick_retrieve(state['question'], top_k=RAG_TOP_K)}


def sources_line(sources) -> str:
    links = [f"[{s.title.translate(_TITLE_BRACKETS)}]({s.source})"
             for s in sources if s.source.startswith(('http://', 'https://'))]
    return 'Sources: ' + ', '.join(links) if links else ''


def format_output(state: RAGState) -> dict:
    response = state.get('response')
    if response:
        response.route = state.get('source_mode')
        if line := sources_line(response.sources):
            response.answer += '\n\n' + line
    return {'response': response}
