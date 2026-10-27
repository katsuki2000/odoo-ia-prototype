"""Helper utilities for documentary RAG generation and citation verification."""

import json
import logging
import re
from typing import Optional

from core.schemas import SourceReference, source_display_title

logger = logging.getLogger(__name__)


_ALIAS = r"S\d{1,2}"
_ALIAS_LIST = rf"{_ALIAS}(?:\s*(?:,|;|/|&|-|–|—|et|and|à|to)\s*{_ALIAS})*"
_ALIAS_PATTERNS = [
    # [Source S2](http://...) or [S2](...): a link whose text is only an alias
    re.compile(rf"^[ \t]*\[\s*(?:sources?\s*)?{_ALIAS_LIST}\s*\]\([^)]*\)[ \t]*|[ \t]*\[\s*(?:sources?\s*)?{_ALIAS_LIST}\s*\]\([^)]*\)", re.IGNORECASE | re.MULTILINE),
    # [Source S2], [Sources S2, S3], [S2]
    re.compile(rf"^[ \t]*\[\s*(?:sources?\s*:?\s*)?{_ALIAS_LIST}\s*\][ \t]*|[ \t]*\[\s*(?:sources?\s*:?\s*)?{_ALIAS_LIST}\s*\]", re.IGNORECASE | re.MULTILINE),
    # (source S2), (sources S3 et S4)
    re.compile(rf"^[ \t]*\(\s*sources?\s*:?\s*{_ALIAS_LIST}\s*\)[ \t]*|[ \t]*\(\s*sources?\s*:?\s*{_ALIAS_LIST}\s*\)", re.IGNORECASE | re.MULTILINE),
]


def strip_source_aliases(answer: str) -> str:
    """Remove the per-call source aliases (S1, S2, ...) the LLM left inside the answer text.

    The aliases are internal: sources are declared in `used_sources` and rendered by the UI.
    Fenced code blocks are left untouched.
    """
    if not answer:
        return answer
    parts = answer.split("```")
    for index in range(0, len(parts), 2):
        text = parts[index]
        for pattern in _ALIAS_PATTERNS:
            text = pattern.sub("", text)
        parts[index] = text
    return "```".join(parts)


def build_source_aliases(chunks: list) -> dict:
    """Build short per-call alias map (S1, S2, ...) over retrieved chunks."""
    return {f"S{i + 1}": chunk for i, chunk in enumerate(chunks)}


def verify_used_sources(used_source_aliases: list, alias_map: dict) -> list:
    """Deterministic verification and deduplication of LLM's cited sources."""
    if not used_source_aliases:
        return []

    valid_aliases = []
    invalid_aliases = []
    seen = set()
    for alias in used_source_aliases:
        if alias not in alias_map:
            invalid_aliases.append(alias)
        elif alias not in seen:
            valid_aliases.append(alias)
            seen.add(alias)

    if invalid_aliases:
        logger.warning(
            "invalid_used_sources: LLM cited unknown source alias(es) %s (available aliases: %s)",
            invalid_aliases, list(alias_map.keys()),
        )

    if not valid_aliases:
        return []

    verified = []
    seen_docs = set()
    for alias, chunk in alias_map.items():
        if alias in valid_aliases:
            meta = chunk.get("metadata") or {}
            doc = chunk.get("document", "")
            snippet = doc[:100] + "..." if len(doc) > 100 else doc
            title = source_display_title(meta)
            source_val = meta.get("source", "unknown")
            dedup_key = (source_val, title)
            if dedup_key in seen_docs:
                continue
            seen_docs.add(dedup_key)
            verified.append(SourceReference(
                source=source_val,
                doc_type=meta.get("type", "document"),
                title=title,
                snippet=snippet,
            ))
    return verified


def compute_rag_confidence(chunks: list, is_out_of_scope: bool = False) -> float:
    """Compute confidence score (0.0 to 1.0) deterministically for documentary branch."""
    if is_out_of_scope or not chunks:
        return 0.0

    top_chunk = chunks[0]
    score = top_chunk.get("score")
    if score is not None:
        try:
            val = float(score)
            return max(0.0, min(1.0, val))
        except (ValueError, TypeError):
            pass

    num = len(chunks)
    if num >= 3:
        return 0.90
    elif num == 2:
        return 0.80
    elif num == 1:
        return 0.70
    return 0.50


def parse_raw_json_answer(raw_text: str) -> Optional[str]:
    """Extract the 'answer' field if raw text is JSON formatted."""
    if not raw_text or not isinstance(raw_text, str):
        return None
    candidate = raw_text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate)
        candidate = candidate.strip()
    if not (candidate.startswith("{") and candidate.endswith("}")):
        return None
    try:
        parsed = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    answer = parsed.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return None
    return answer
