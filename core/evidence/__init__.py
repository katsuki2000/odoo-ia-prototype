"""
core/evidence/__init__.py

Regroupement (todo/contexte.txt Section 649-653) : evidence.py, evidence_check.py, evidence_collector.py, evidence_sufficiency.py.
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
    collect_and_clear_evidence,
)
from .evidence_sufficiency import (
    EvidenceSufficiencyStatus,
    EvidenceSufficiencyResult,
    assess_evidence_sufficiency,
)

__all__ = [
    "EvidenceSourceType",
    "stable_content_hash",
    "Evidence",
    "make_evidence",
    "check_evidence",
    "start_evidence_collection",
    "record_evidence",
    "collect_and_clear_evidence",
    "EvidenceSufficiencyStatus",
    "EvidenceSufficiencyResult",
    "assess_evidence_sufficiency",
]
