"""
Semantic Ontology Subpackage -- behavioral/technical tags and their
query/coverage helpers (Bloc P2).
"""

from code_intelligence.ontology.tags import BehavioralTag, TechnicalTag
from code_intelligence.ontology.query import tags_for_node_attrs, get_tagged_nodes_for_model
from code_intelligence.ontology.coverage import (
    NODE_TYPES_NEVER_TAGGED,
    NODE_TYPES_TECHNICAL_ONLY_BY_DESIGN,
    NODE_TYPES_ALWAYS_FULLY_TAGGED,
    NODE_TYPES_CONDITIONALLY_TAGGED,
    compute_ontology_coverage,
    detect_unexpected_gaps,
)

__all__ = [
    "BehavioralTag",
    "TechnicalTag",
    "tags_for_node_attrs",
    "get_tagged_nodes_for_model",
    "NODE_TYPES_NEVER_TAGGED",
    "NODE_TYPES_TECHNICAL_ONLY_BY_DESIGN",
    "NODE_TYPES_ALWAYS_FULLY_TAGGED",
    "NODE_TYPES_CONDITIONALLY_TAGGED",
    "compute_ontology_coverage",
    "detect_unexpected_gaps",
]
