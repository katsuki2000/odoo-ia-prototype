"""
core/routing/__init__.py

Regroupement (todo/contexte.txt Section 649-653) : routing_keywords.py, routing.py.
"""

from .routing_keywords import (
    ERP_TYPES,
    ROUTING_CONFLICT_PRIORITY,
    ERP_KEYWORDS,
    CODE_INTEL_KEYWORDS,
    QUANTITATIVE_TERMS,
    DOC_KEYWORDS,
    DATA_TERMS,
    DOC_ANCHORS,
    THRESHOLD_QUERY_TERMS,
    CONDITIONAL_AMOUNT_TERMS,
    _fold_accents,
    _fold_keywords,
    ERP_KEYWORDS_FOLDED,
    CODE_INTEL_KEYWORDS_FOLDED,
    QUANTITATIVE_TERMS_FOLDED,
    DOC_KEYWORDS_FOLDED,
    DATA_TERMS_FOLDED,
    DOC_ANCHORS_FOLDED,
    THRESHOLD_QUERY_TERMS_FOLDED,
    CONDITIONAL_AMOUNT_TERMS_FOLDED,
)
from .routing import (
    logger,
    _VALID_ROUTES,
    _sticky_route_or_default,
    _sticky_concept_or_resolve,
    route,
    route_decision,
)

__all__ = [
    "ERP_TYPES",
    "ROUTING_CONFLICT_PRIORITY",
    "ERP_KEYWORDS",
    "CODE_INTEL_KEYWORDS",
    "QUANTITATIVE_TERMS",
    "DOC_KEYWORDS",
    "DATA_TERMS",
    "DOC_ANCHORS",
    "THRESHOLD_QUERY_TERMS",
    "CONDITIONAL_AMOUNT_TERMS",
    "_fold_accents",
    "_fold_keywords",
    "ERP_KEYWORDS_FOLDED",
    "CODE_INTEL_KEYWORDS_FOLDED",
    "QUANTITATIVE_TERMS_FOLDED",
    "DOC_KEYWORDS_FOLDED",
    "DATA_TERMS_FOLDED",
    "DOC_ANCHORS_FOLDED",
    "THRESHOLD_QUERY_TERMS_FOLDED",
    "CONDITIONAL_AMOUNT_TERMS_FOLDED",
    "logger",
    "_VALID_ROUTES",
    "_sticky_route_or_default",
    "_sticky_concept_or_resolve",
    "route",
    "route_decision",
]
