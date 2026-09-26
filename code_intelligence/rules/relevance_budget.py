"""
code_intelligence/rules/relevance_budget.py

Generic, tool-agnostic relevance ranking and protected-minimum budget
water-filling for assembling several deterministic-tool text "blocks"
under a single character budget.

Extracted from security_evidence.py (todo/contexte.txt sections 824-846),
which built this mechanism first and only for analyze_security_locks.
Section 948 (point 1) confirmed that who_has_access_to, evaluate_record_rules
and analyze_method_override_chain still fell back to plain head-truncation
(_truncate_observation, code_intelligence/agent/context.py): when a cut is
needed, that mechanism keeps whichever blocks happen to sit first in FIXED
positional/source order and drops everything after, regardless of which
block is actually relevant to the question being asked. Section 950
generalizes the security-lock mechanism to those three tools by moving its
tool-agnostic primitives here.
"""

from __future__ import annotations

from typing import List, Optional
import re

from code_intelligence.utils import waterfill_budget
from code_intelligence.agent.context import _truncate_observation

_STOPWORDS = frozenset({
    "le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "est",
    "peut", "dont", "sur", "par", "pour", "avec", "dans", "ce", "cette",
    "ces", "aux", "que", "qui", "elle", "plus", "moins", "sans", "tout",
    "the", "of", "to", "in", "is", "are", "and", "for", "on", "with",
    "this", "that", "can", "not", "your", "you", "has", "have", "been",
})


def _significant_tokens(text: str) -> set:
    words = re.findall(r"[a-zA-ZÀ-ÿ_]+", text.lower())
    return {w for w in words if len(w) > 3 and w not in _STOPWORDS}


def _relevance_score(text: str, question: Optional[str]) -> float:
    if not question or not text:
        return 0.0
    from rapidfuzz import fuzz
    base = fuzz.token_set_ratio(question.lower(), text.lower())
    overlap = _significant_tokens(question) & _significant_tokens(text)
    return base + 15 * len(overlap)


def _rerank_by_relevance(items: list, text_fn, question: Optional[str]) -> list:
    """Stable-sort `items` by _relevance_score(text_fn(item), question),
    descending. Returns `items` UNCHANGED (same order, same list identity
    semantics) when `question` is falsy -- e.g. isolated unit tests that
    call a formatter directly without going through the agent loop's
    set_current_question, and existing tests asserting a specific
    source/positional order, are unaffected."""
    if not question:
        return items
    return sorted(items, key=lambda item: _relevance_score(text_fn(item), question), reverse=True)


def _protected_prefix_end(text: str) -> int:
    """Character offset covering the header/marker line plus the first
    substantive finding line that follows it (and, when present, a second
    bullet-continuation line right after). Guarantees every non-empty,
    multi-line block keeps at least one complete, highest-priority finding
    line intact instead of relying on plain water-filling alone, which can
    land an allocation mid-line and drop the whole line once
    _truncate_observation rewinds to the previous newline.

    A single-line block (no internal newline -- e.g. a compact "no
    findings" stub, or a one-line summary already reduced to its
    essential form) returns 0: there is nothing to protect A PART of, so
    such a block is handled all-or-nothing by
    _waterfill_with_protected_minimum below rather than risking a
    half-cut fragment.
    """
    lines = text.split("\n")
    if len(lines) <= 1:
        return 0
    protect_upto = 2
    if len(lines) > 2 and lines[2].lstrip().startswith("*"):
        protect_upto = 3
    return min(len("\n".join(lines[:protect_upto])), len(text))


def _waterfill_with_protected_minimum(
    sizes: List[int], texts: List[str], budget: int, priority: Optional[List[int]] = None
) -> List[int]:
    """Water-fill `budget` across `sizes`, but first guarantee each
    non-empty item its `_protected_prefix_end` minimum (capped at the
    item's own size) before water-filling the remainder proportionally.

    When the protected minimums together do not fit in `budget`, plain
    water-filling would give every block a tiny, roughly-equal,
    budget-unaware slice -- putting the single most important block on
    equal footing with unrelated ones. Instead, greedily grant FULL
    protected minimums to blocks in `priority` order (highest first;
    defaults to each item's own size when no external priority is
    supplied) until the budget runs out -- every included block keeps one
    complete, uncut message rather than every block getting an equally
    broken partial one. Blocks that do not fit at all get 0, not a
    useless fragment.
    """
    protected = [min(_protected_prefix_end(t), s) if s else 0 for t, s in zip(texts, sizes)]
    protected_total = sum(protected)
    if protected_total > budget:
        order = sorted(
            range(len(sizes)),
            key=lambda i: (priority[i] if priority else sizes[i]),
            reverse=True,
        )
        alloc = [0] * len(sizes)
        remaining = budget
        for i in order:
            if protected[i] and protected[i] <= remaining:
                alloc[i] = protected[i]
                remaining -= protected[i]
        return alloc
    extra_sizes = [s - p for s, p in zip(sizes, protected)]
    extra_budget = budget - protected_total
    extra_alloc = waterfill_budget(extra_sizes, extra_budget)
    alloc = [p + e for p, e in zip(protected, extra_alloc)]
    # An item with protected==0 has no internal newline for
    # _truncate_observation to rewind to (it is a single atomic line).
    # Handing it a tiny partial share is worse than useless: with no
    # newline to cut back to, _truncate_observation hard-cuts mid-line and
    # still appends its truncation marker, so the actual output can end up
    # LONGER than the tiny cap it was given, and even without that
    # overshoot, half a line is just noise. All-or-nothing for these
    # instead.
    for i, (s, a, p) in enumerate(zip(sizes, alloc, protected)):
        if p == 0 and 0 < a < s:
            alloc[i] = 0
    return alloc


def assemble_relevance_ranked_blocks(
    blocks: List[str],
    budget: int,
    question: Optional[str] = None,
    separator: str = "\n",
) -> str:
    """Join `blocks` under `budget` chars, in their ORIGINAL order, but
    decide which block(s) survive -- fully or partially -- by protected-
    minimum + relevance-to-`question` priority rather than plain
    positional head-truncation. Falls straight through (no reordering, no
    dropped block) when everything already fits, so callers with no
    question context (or whose blocks always fit) see byte-identical
    output to a plain separator.join(blocks).

    This is the tool-agnostic generalization of
    security_evidence.assemble_security_lock_blocks (single-tier: no
    essential/exception split, no empty-block compaction -- those two
    remain specific to analyze_security_locks' own two-density-tier
    format)."""
    if not blocks:
        return ""
    if budget <= 0:
        return _truncate_observation("", 0)

    sizes = [len(b) for b in blocks]
    sep_overhead = max(0, len(blocks) - 1) * len(separator)
    if sum(sizes) + sep_overhead <= budget:
        return separator.join(blocks)

    priority = [_relevance_score(b, question) for b in blocks] if question else None
    alloc = _waterfill_with_protected_minimum(sizes, blocks, budget, priority=priority)

    parts: List[str] = []
    for block, cap in zip(blocks, alloc):
        if cap <= 0:
            continue
        parts.append(block if cap >= len(block) else _truncate_observation(block, cap))
    return separator.join(parts)
