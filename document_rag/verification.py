"""
document_rag/verification.py

Deterministic completeness check for documentary answers: verifies that list
and table items present in cited source chunks are restituted in the answer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from core.evaluation.oracles.documentation import (
    distinctive_terms,
    parse_sections,
)
from core.evaluation.protocol_metrics import normalize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DocumentaryCompletenessReport:
    total_expected_items: int = 0
    restituted_items: int = 0
    missing_items: list[str] = field(default_factory=list)

    @property
    def is_exhaustive(self) -> bool:
        return len(self.missing_items) == 0

    @property
    def recall(self) -> float:
        if self.total_expected_items == 0:
            return 1.0
        return self.restituted_items / self.total_expected_items


def verify_documentary_completeness(
    answer: str,
    chunks: Sequence[Mapping[str, Any]],
) -> DocumentaryCompletenessReport:
    """Verify that all items of any list/procedure in the chunks appear in the answer."""
    normalized_answer = normalize(answer)
    all_items: list[str] = []
    missing: list[str] = []

    for chunk in chunks:
        doc_text = chunk.get("document", "")
        source_name = (chunk.get("metadata") or {}).get("source", "document")
        sections = parse_sections(doc_text, source_name)
        for section in sections:
            items = section.items
            if len(items) < 2:
                continue
            for i, item in enumerate(items):
                all_items.append(item)
                others = items[:i] + items[i + 1:]
                terms = distinctive_terms(item, others)
                matched = any(normalize(t) in normalized_answer for t in terms)
                if not matched:
                    missing.append(item)

    total = len(all_items)
    restituted = total - len(missing)
    if missing:
        logger.info(
            "Documentary completeness: %d/%d items matched. %d missing from answer.",
            restituted, total, len(missing),
        )

    return DocumentaryCompletenessReport(
        total_expected_items=total,
        restituted_items=restituted,
        missing_items=missing,
    )
