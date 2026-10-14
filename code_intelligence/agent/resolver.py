"""Business term to technical symbol resolver: maps functional language to graph models and modules."""

from typing import Optional

from .aliases import (
    BUSINESS_ALIASES,
    NATIVE_MODEL_SYNONYMS,
    normalize_alias_text,
    BUSINESS_ALIASES_NFC,
    _ALIAS_PATTERNS,
)
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
from .resolution.alias_lookup import resolve_static_alias
from .resolution.arbitration import (
    _ARBITRATION_SYSTEM_PROMPT,
    _build_arbitration_prompt,
    _llm_arbitrate,
)
from .resolution.candidates import (
    AMBIGUITY_GAP_THRESHOLD,
    WIDENED_CANDIDATE_LIMIT,
    WIDENED_CANDIDATE_THRESHOLD,
    _arbitration_candidates,
    _candidate_contexts,
    _deterministic_tiebreak,
)
from .resolution.dense_lookup import resolve_dense_retrieval
from .resolution.exact_mention import resolve_exact_mention
from .resolution.fuzzy_lookup import resolve_fuzzy_match
from .semantic_retrieval import SEMANTIC_STATUS_DIAGNOSTIC_KEY


def resolve_business_term(
    query_text: str,
    G=None,
    llm=None,
    *,
    language: Optional[str] = None,
    use_static_aliases: bool = False,
) -> ResolvedConcept:
    """Resolve a natural language query into a technical Odoo model/module.

    Exact mentions are resolved first. Dense retrieval proposes candidates;
    lexical matching and bounded arbitration resolve disagreements.

    Static aliases are off by default. Pass use_static_aliases=True only for
    backward-compatible evaluation (E1 R0).
    """
    if not query_text:
        return ResolvedConcept(
            user_term="",
            is_resolved=False,
            reason="Empty query text provided.",
        )

    clean_query = normalize_alias_text(query_text.lower().strip())
    aliases = BUSINESS_ALIASES_NFC if use_static_aliases else {}
    alias_patterns = _ALIAS_PATTERNS if use_static_aliases else {}

    resolved = resolve_exact_mention(clean_query, query_text, G, aliases, alias_patterns)
    if resolved is not None:
        return resolved

    if use_static_aliases:
        resolved = resolve_static_alias(clean_query, G, aliases, alias_patterns)
        if resolved is not None:
            return resolved

    dense = resolve_dense_retrieval(query_text, G, language)
    resolved = resolve_fuzzy_match(
        query_text, clean_query, G, llm, language, use_static_aliases,
        semantic_candidates=dense.candidates,
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
    "BUSINESS_ALIASES",
    "NATIVE_MODEL_SYNONYMS",
    "normalize_alias_text",
    "BUSINESS_ALIASES_NFC",
    "_ALIAS_PATTERNS",
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
