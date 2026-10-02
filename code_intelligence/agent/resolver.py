"""Business term to technical symbol resolver: maps functional language to graph models and modules."""

from typing import Optional

from .aliases import (
    BUSINESS_ALIASES,
    NATIVE_MODEL_SYNONYMS,
    _nfc,
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
from .resolution.exact_mention import resolve_exact_mention
from .resolution.fuzzy_lookup import resolve_fuzzy_match


def resolve_business_term(
    query_text: str,
    G=None,
    llm=None,
    active_model: Optional[str] = None,
    *,
    language: Optional[str] = None,
    use_static_aliases: bool = True,
) -> ResolvedConcept:
    """Resolve a natural language query into a technical Odoo model/module."""
    if not query_text:
        return ResolvedConcept(
            user_term="",
            is_resolved=False,
            reason="Empty query text provided.",
        )

    clean_query = _nfc(query_text.lower().strip())
    aliases = BUSINESS_ALIASES_NFC if use_static_aliases else {}
    alias_patterns = _ALIAS_PATTERNS if use_static_aliases else {}

    resolved = resolve_exact_mention(clean_query, query_text, G, aliases, alias_patterns)
    if resolved is not None:
        return resolved

    resolved = resolve_static_alias(clean_query, G, aliases, alias_patterns)
    if resolved is not None:
        return resolved

    if active_model and G is not None and G.has_node(f"model:{active_model}"):
        return ResolvedConcept(
            user_term=query_text,
            resolved_models=[active_model],
            confidence=0.9,
            source_step="active_context",
            is_resolved=True,
            reason=f"No textual match in the question itself; resolved from active UI context (model={active_model})",
        )

    resolved = resolve_fuzzy_match(query_text, clean_query, G, llm, language, use_static_aliases)
    if resolved is not None:
        return resolved

    return ResolvedConcept(
        user_term=query_text,
        is_resolved=False,
        confidence=0.0,
        source_step="unresolved",
        reason="No business alias or graph model match found.",
    )


__all__ = [
    "BUSINESS_ALIASES",
    "NATIVE_MODEL_SYNONYMS",
    "_nfc",
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
