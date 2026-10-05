"""Pure mapping from a raw system response to the scored case result."""

from __future__ import annotations

from typing import Mapping

from config.settings import MASSIVE_EXTRACTION_REFUSAL_MSG, PROMPT_INJECTION_REFUSAL_MSG
from core.evidence.evidence_sufficiency import EvidenceSufficiencyStatus
from core.evaluation.frozen_cases import FrozenCase
from core.evaluation.protocol_metrics import CaseResult

INTERNAL_ERROR_MESSAGE = "Une erreur interne s'est produite lors de l'exécution du pipeline."
REFUSAL_MESSAGES = (MASSIVE_EXTRACTION_REFUSAL_MSG, PROMPT_INJECTION_REFUSAL_MSG)
ROUTE_SOURCES = {
    "code_intelligence": ("code",),
    "donnees_erp": ("runtime",),
    "documentaire": ("internal_docs",),
    "hybride": ("runtime", "internal_docs"),
}
EVIDENCE_KINDS = {"code": "graph", "orm": "orm"}
INSUFFICIENT = EvidenceSufficiencyStatus.INSUFFICIENT.value


def classify_outcome(raw: Mapping) -> str:
    answer = raw.get("answer")
    if raw.get("error") or answer == INTERNAL_ERROR_MESSAGE:
        return "error"
    if raw.get("omitted_for_authorization") or answer in REFUSAL_MESSAGES:
        return "refusal"
    verdict = str((raw.get("ci_evidence_sufficiency") or {}).get("status", "")).lower()
    if verdict == INSUFFICIENT and not raw.get("rag_fallback"):
        return "abstention"
    return "answered"


def sources_used(raw: Mapping) -> tuple:
    return ROUTE_SOURCES.get(raw.get("route"), ())


def resolved_objects(raw: Mapping) -> tuple:
    concept = raw.get("resolved_concept") or {}
    if not concept.get("is_resolved", False):
        return ()
    models = tuple(f"model:{name}" for name in concept.get("resolved_models", ()))
    modules = tuple(f"module:{name}" for name in concept.get("resolved_modules", ()))
    return models + modules


def evidence_pairs(raw: Mapping) -> tuple:
    dossier = tuple(
        (EVIDENCE_KINDS[item["source_type"]], item["source"])
        for item in raw.get("evidence_dossier") or ()
        if item.get("source_type") in EVIDENCE_KINDS
    )
    documents = tuple(("document", item["source"]) for item in raw.get("sources") or ())
    return dossier + documents


def to_case_result(case: FrozenCase, raw: Mapping) -> CaseResult:
    return CaseResult(
        case_id=case.case_id,
        outcome=classify_outcome(raw),
        answer=raw.get("answer") or "",
        sources_used=sources_used(raw),
        resolved_objects=resolved_objects(raw),
        evidence=evidence_pairs(raw),
    )
