"""
code_intelligence/deterministic/common.py

Shared constants and enums for deterministic knowledge graph queries.
"""

from enum import Enum

NOT_FOUND_MARKER = "was not found in the indexed knowledge graph"


class QueryStatus(Enum):
    FOUND = "found"
    EMPTY = "empty"
    NOT_FOUND = "not_found"
