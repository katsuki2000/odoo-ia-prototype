"""
code_intelligence/business_resolver/

Package for resolving business concepts and natural language queries to technical Odoo models and modules.
"""

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
from .arbitration import (
    AMBIGUITY_GAP_THRESHOLD,
    WIDENED_CANDIDATE_THRESHOLD,
    WIDENED_CANDIDATE_LIMIT,
    _llm_arbitrate,
)
from .prompts import (
    _ARBITRATION_SYSTEM_PROMPT,
    _build_arbitration_prompt,
)
from .resolver import resolve_business_term

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
    "resolve_business_term",
]
