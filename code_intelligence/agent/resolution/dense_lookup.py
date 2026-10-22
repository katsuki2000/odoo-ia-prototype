"""Retrieve semantic model candidates from labels in the active instance graph.

The embedding model and backend are controlled by RESOLVER_SEMANTIC_* env vars.
"""

import logging
from typing import NamedTuple, Optional

from .candidates import HYBRID_SEMANTIC_LIMIT
from .semantic_retrieval import (
    SemanticRetrievalStatus,
    retrieve_semantic_model_candidates_scored,
)

_logger = logging.getLogger(__name__)

DENSE_MIN_SCORE = 0.25


class DenseResolution(NamedTuple):
    """Dense retrieval candidates; semantic similarity alone never resolves a model."""

    status: Optional[SemanticRetrievalStatus]
    candidates: tuple[str, ...] = ()


def resolve_dense_retrieval(
    query_text: str,
    G,
    language: Optional[str],
) -> DenseResolution:
    """Retrieve plausible model candidates; semantic scores alone never select one."""
    if G is None:
        return DenseResolution(None)

    scored, status = retrieve_semantic_model_candidates_scored(
        query_text, G, language, limit=HYBRID_SEMANTIC_LIMIT,
    )
    if status in (SemanticRetrievalStatus.DISABLED, SemanticRetrievalStatus.ERROR):
        _logger.debug("Dense retrieval skipped (status=%s); falling through.", status.value)
        return DenseResolution(status)
    if not scored:
        return DenseResolution(status)

    _, top_score = scored[0]
    if top_score < DENSE_MIN_SCORE:
        _logger.debug(
            "Dense top score %.3f below threshold %.3f; falling through.",
            top_score, DENSE_MIN_SCORE,
        )
        return DenseResolution(status)

    candidates = tuple(model for model, score in scored if score >= DENSE_MIN_SCORE)
    _logger.debug(
        "Dense retrieval produced %d candidates; selection is deferred to hybrid resolution.",
        len(candidates),
    )
    return DenseResolution(status, candidates)
