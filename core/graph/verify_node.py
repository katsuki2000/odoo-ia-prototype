"""Verify answers against this request's evidence."""

import logging

from config.settings import ANSWER_VERIFIER_MODE
from core.evidence.disclosure import filter_disclosed_evidence
from core.evidence.evidence_collector import peek_turn_evidence
from core.graph.graph_nodes import answered_by_documents
from core.state import RAGState
from core.verification.base_methods import default_base_model_methods
from core.schemas import VerifierMode
from core.verification.context import VerificationContext, flatten_numeric_values
from core.verification.verifier import verify_answer_claims

logger = logging.getLogger(__name__)
VERIFIER_MODE = VerifierMode.parse(ANSWER_VERIFIER_MODE)


def _evidence(state: RAGState) -> tuple[tuple[str, ...], tuple[float, ...]]:
    if answered_by_documents(state):
        return tuple(chunk.get('document', '') for chunk in state.get('retrieved_chunks') or []), ()
    turn_evidence = filter_disclosed_evidence(peek_turn_evidence())
    texts = (state.get('raw_tool_output') or '', *(item.claim for item in turn_evidence))
    numbers = tuple(number for item in turn_evidence for number in flatten_numeric_values(item.value))
    return texts, numbers


def _build_context(state: RAGState) -> VerificationContext:
    texts, numbers = _evidence(state)
    return VerificationContext(
        texts=texts, numeric_values=numbers, base_methods=default_base_model_methods())


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
