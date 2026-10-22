"""Business term to technical symbol resolver: maps functional language to graph models and modules."""

from typing import Optional

from .matching import (
    ResolvedConcept,
    _FUZZY_INDEX_CACHE,
    _build_fuzzy_index,
    _GENERIC_FIELD_NAMES,
    _find_exact_technical_model_mentions,
    _find_exact_technical_module_mentions,
    _specificity_score,
    rank_by_specificity,
    _fuzzy_match_graph,
)
from .arbitration import (
    _ARBITRATION_SYSTEM_PROMPT,
    _build_arbitration_prompt,
    _llm_arbitrate,
)
from .candidates import (
    AMBIGUITY_GAP_THRESHOLD,
    WIDENED_CANDIDATE_LIMIT,
    WIDENED_CANDIDATE_THRESHOLD,
    _arbitration_candidates,
    _candidate_contexts,
    _deterministic_tiebreak,
)
from .dense_lookup import resolve_dense_retrieval
from .exact_mention import resolve_exact_mention
from .fuzzy_lookup import resolve_fuzzy_match
from .label_mention import quoted_model_labels
from .semantic_retrieval import SEMANTIC_STATUS_DIAGNOSTIC_KEY
from ..text_normalization import normalize_query_text


def resolve_business_term(
    query_text: str,
    G=None,
    llm=None,
    *,
    language: Optional[str] = None,
) -> ResolvedConcept:
    """Resolve a natural language query into a technical Odoo model/module.

    Exact technical names are resolved first. Quoted instance labels and dense retrieval propose candidates;
    lexical matching and bounded arbitration resolve disagreements.
    """
    if not query_text:
        return ResolvedConcept(
            user_term="",
            is_resolved=False,
            reason="Empty query text provided.",
        )

    clean_query = normalize_query_text(query_text.lower().strip())

    resolved = resolve_exact_mention(clean_query, query_text, G)
    if resolved is not None:
        return resolved

    dense = resolve_dense_retrieval(query_text, G, language)
    resolved = resolve_fuzzy_match(
        query_text, clean_query, G, llm, language, semantic_candidates=dense.candidates,
        quoted_labels=quoted_model_labels(clean_query, G),
    )
    if resolved is None:
        resolved = ResolvedConcept(
            user_term=query_text,
            is_resolved=False,
            confidence=0.0,
            source_step="unresolved",
            reason="No match found in instance labels or graph.",
        )
    if dense.status is not None:
        resolved.diagnostics.setdefault(SEMANTIC_STATUS_DIAGNOSTIC_KEY, dense.status.value)
    return resolved


__all__ = [
    "ResolvedConcept",
    "_FUZZY_INDEX_CACHE",
    "_build_fuzzy_index",
    "_GENERIC_FIELD_NAMES",
    "_find_exact_technical_model_mentions",
    "_find_exact_technical_module_mentions",
    "_specificity_score",
    "rank_by_specificity",
    "_fuzzy_match_graph",
    "AMBIGUITY_GAP_THRESHOLD",
    "WIDENED_CANDIDATE_THRESHOLD",
    "WIDENED_CANDIDATE_LIMIT",
    "_ARBITRATION_SYSTEM_PROMPT",
    "_build_arbitration_prompt",
    "_llm_arbitrate",
    "_arbitration_candidates",
    "_candidate_contexts",
    "_deterministic_tiebreak",
    "resolve_business_term",
]
