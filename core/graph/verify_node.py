"""Verify answers against this request's evidence and investigation graph."""

import logging
from typing import Optional, Tuple

import networkx as nx

from config.settings import ANSWER_VERIFIER_MODE
from core.evidence.evidence_collector import peek_turn_evidence
from core.graph.graph_nodes import answered_by_documents
from core.state import RAGState
from core.verification.base_methods import default_base_model_methods
from core.verification.claims import VerifierMode
from core.verification.context import VerificationContext, flatten_numeric_values
from core.verification.verifier import verify_answer_claims

logger = logging.getLogger(__name__)
VERIFIER_MODE = VerifierMode.parse(ANSWER_VERIFIER_MODE)


def _load_graph(language: Optional[str]) -> Optional[nx.DiGraph]:
    from code_intelligence.graph import get_code_intelligence_graph
    try:
        return get_code_intelligence_graph(
            translation_languages=[language] if language else None, request_language=language)
    except Exception as error:
        logger.warning('Answer verifier: knowledge graph unavailable (%s)', type(error).__name__)
        return None


def _evidence(state: RAGState) -> Tuple[Tuple[str, ...], Tuple[float, ...]]:
    if answered_by_documents(state):
        return tuple(chunk.get('document', '') for chunk in state.get('retrieved_chunks') or []), ()
    from code_intelligence.rules.security_locks import filter_disclosed_evidence
    turnEvidence = filter_disclosed_evidence(
        peek_turn_evidence(), state.get('sensitive_evidence_allowed', False))
    texts = (state.get('raw_tool_output') or '', *(item.claim for item in turnEvidence))
    numbers = tuple(number for item in turnEvidence for number in flatten_numeric_values(item.value))
    return texts, numbers


def _build_context(state: RAGState) -> VerificationContext:
    texts, numbers = _evidence(state)
    graph = None
    if not answered_by_documents(state):
        graph = state.get('knowledge_graph')
        if graph is None:
            graph = _load_graph(state.get('language'))
    return VerificationContext(
        texts=texts, numeric_values=numbers, graph=graph,
        base_methods=default_base_model_methods())


def verify_answer(state: RAGState) -> dict:
    response = state.get('response')
    if VERIFIER_MODE is VerifierMode.OFF or response is None or not response.answer:
        return {}
    try:
        verified, report = verify_answer_claims(response.answer, _build_context(state), VERIFIER_MODE)
    except Exception:
        logger.exception('Answer verifier failed; answer left unverified')
        return {}
    response.verification = report
    if VERIFIER_MODE is VerifierMode.ENFORCE:
        response.answer = verified
    return {'response': response}
