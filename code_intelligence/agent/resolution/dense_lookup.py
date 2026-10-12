"""Resolution step: dense semantic retrieval on graph instance labels.

Replaces the static alias table with a retrieval based on actual instance
labels (business_labels, descriptions, menu names) embedded at graph build
time. The embedding model and backend are controlled by env vars
(RESOLVER_SEMANTIC_*).
"""

import logging
from typing import Optional

from ..matching import ResolvedConcept
from ..semantic_retrieval import (
    SemanticRetrievalStatus,
    retrieve_semantic_model_candidates_scored,
)

_logger = logging.getLogger(__name__)

DENSE_SCORE_GAP_THRESHOLD = 0.10
DENSE_MIN_SCORE = 0.25


def resolve_dense_retrieval(
    query_text: str,
    G,
    language: Optional[str],
) -> Optional[ResolvedConcept]:
    """Resolve through dense retrieval on graph labels; None when unavailable or ambiguous."""
    if G is None:
        return None

    scored, status = retrieve_semantic_model_candidates_scored(
        query_text, G, language, limit=10,
    )
    if status in (SemanticRetrievalStatus.DISABLED, SemanticRetrievalStatus.ERROR):
        _logger.debug("Dense retrieval skipped (status=%s); falling through.", status.value)
        return None
    if not scored:
        return None

    top_model, top_score = scored[0]
    if top_score < DENSE_MIN_SCORE:
        _logger.debug(
            "Dense top score %.3f below threshold %.3f; falling through.",
            top_score, DENSE_MIN_SCORE,
        )
        return None

    is_ambiguous = (
        len(scored) >= 2
        and (top_score - scored[1][1]) < DENSE_SCORE_GAP_THRESHOLD
    )
    if is_ambiguous:
        _logger.debug(
            "Dense retrieval ambiguous: %s (%.3f) vs %s (%.3f); falling through to arbitration.",
            top_model, top_score, scored[1][0], scored[1][1],
        )
        return None

    return ResolvedConcept(
        user_term=query_text,
        resolved_models=[top_model],
        confidence=round(top_score, 3),
        source_step="dense_retrieval",
        is_resolved=True,
        reason=(
            f"Dense retrieval on instance labels: {top_model} "
            f"(score={top_score:.3f}, gap={top_score - scored[1][1]:.3f})"
            if len(scored) >= 2
            else f"Dense retrieval on instance labels: {top_model} (score={top_score:.3f}, sole candidate above threshold)"
        ),
        diagnostics={"semantic_retrieval": status.value},
    )
