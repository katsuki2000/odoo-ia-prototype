"""
core/evidence/__init__.py

Regroupement (todo/contexte.txt Section 649-653) : evidence.py, evidence_check.py, evidence_collector.py, evidence_sufficiency.py.
"""

from .evidence import (
    EvidenceSourceType,
    _canonical_json,
    stable_content_hash,
    Evidence,
    make_evidence,
)
from .evidence_check import (
    check_evidence,
)
from .evidence_collector import (
    logger,
    _turn_evidence_ctx,
    start_evidence_collection,
    record_evidence,
    collect_and_clear_evidence,
)
from .evidence_sufficiency import (
    EvidenceSufficiencyStatus,
    _NO_DATA_MARKER,
    _OUT_OF_SCOPE_MODEL_MARKER,
    _DYNAMIC_UNCERTAINTY_MARKER,
    _INDETERMINATE_FACT_MARKER,
    _EXECUTION_ERROR_MARKER,
    _NON_EVIDENCE_OBSERVATION_MARKERS,
    EvidenceSufficiencyResult,
    _is_relevant_observation,
    _has_execution_failure,
    assess_evidence_sufficiency,
)

__all__ = [
    "EvidenceSourceType",
    "_canonical_json",
    "stable_content_hash",
    "Evidence",
    "make_evidence",
    "check_evidence",
    "logger",
    "_turn_evidence_ctx",
    "start_evidence_collection",
    "record_evidence",
    "collect_and_clear_evidence",
    "EvidenceSufficiencyStatus",
    "_NO_DATA_MARKER",
    "_OUT_OF_SCOPE_MODEL_MARKER",
    "_DYNAMIC_UNCERTAINTY_MARKER",
    "_INDETERMINATE_FACT_MARKER",
    "_EXECUTION_ERROR_MARKER",
    "_NON_EVIDENCE_OBSERVATION_MARKERS",
    "EvidenceSufficiencyResult",
    "_is_relevant_observation",
    "_has_execution_failure",
    "assess_evidence_sufficiency",
]
