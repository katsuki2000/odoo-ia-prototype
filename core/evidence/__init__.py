"""
core/evidence/__init__.py

Regroupement : evidence.py, evidence_check.py, evidence_collector.py.
"""

from .evidence import (
    EvidenceSourceType,
    stable_content_hash,
    Evidence,
    make_evidence,
)
from .evidence_check import (
    check_evidence,
)
from .evidence_collector import (
    start_evidence_collection,
    record_evidence,
    peek_turn_evidence,
    collect_and_clear_evidence,
)

__all__ = [
    "EvidenceSourceType",
    "stable_content_hash",
    "Evidence",
    "make_evidence",
    "check_evidence",
    "start_evidence_collection",
    "record_evidence",
    "peek_turn_evidence",
    "collect_and_clear_evidence",
]
