"""
core/graph/verify_node.py

Deterministic answer verification node, inserted before format_output
(todo/contexte.txt sections 1119-1129).
"""

import logging
from typing import Optional, Tuple

import networkx as nx

from config.settings import ANSWER_VERIFIER_MODE
from core.evidence.evidence_collector import peek_turn_evidence
from core.graph.graph_nodes import answered_by_documents
from core.output import sanitize_html_to_markdown
from core.state import RAGState
from core.verification.base_methods import default_base_model_methods
from core.verification.claims import VerifierMode
from core.verification.context import VerificationContext, flatten_numeric_values
from core.verification.verifier import verify_answer_claims

logger = logging.getLogger(__name__)

VERIFIER_MODE = VerifierMode.parse(ANSWER_VERIFIER_MODE)


def _load_graph(language: Optional[str]) -> Optional[nx.DiGraph]:
    from code_intelligence.graph.loader import get_code_intelligence_graph

    try:
        return get_code_intelligence_graph(
            translation_languages=[language] if language else None,
            request_language=language,
        )
    except Exception as error:
        logger.warning("Answer verifier: knowledge graph unavailable (%s)", error)
        return None


def _evidence(state: RAGState) -> Tuple[Tuple[str, ...], Tuple[float, ...]]:
    if answered_by_documents(state):
        return tuple(chunk.get("document", "") for chunk in state.get("retrieved_chunks") or []), ()
    turn_evidence = peek_turn_evidence()
    texts = (state.get("raw_tool_output") or "", *(item.claim for item in turn_evidence))
    numbers = tuple(number for item in turn_evidence for number in flatten_numeric_values(item.value))
    return texts, numbers


def _build_context(state: RAGState) -> VerificationContext:
    texts, numbers = _evidence(state)
    return VerificationContext(
        texts=(state.get("question", ""), *texts),
        numeric_values=numbers,
        graph=_load_graph(state.get("language")),
        base_methods=default_base_model_methods(),
    )


def verify_answer(state: RAGState) -> dict:
    """Attach the verification report; in enforce mode also write the answer without unsupported claims."""
    response = state.get("response")
    if VERIFIER_MODE is VerifierMode.OFF or response is None or not response.answer:
        return {}
    try:
        context = _build_context(state)
        verified, report = verify_answer_claims(
            sanitize_html_to_markdown(response.answer), context, VERIFIER_MODE,
        )
    except Exception:
        logger.exception("Answer verifier failed; answer left unverified")
        return {}
    response.verification = report
    if VERIFIER_MODE is VerifierMode.ENFORCE:
        response.answer = verified
    return {"response": response}
