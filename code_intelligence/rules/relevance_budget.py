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


def _rerank_by_relevance(items: list, text_fn, question: Optional[str], bonus_fn=None) -> list:
    """Stable-sort `items` by _relevance_score(text_fn(item), question)
    (plus an optional deterministic `bonus_fn(item)` added on top),
    descending. Returns `items` UNCHANGED (same order, same list identity
    semantics) when `question` is falsy -- e.g. isolated unit tests that
    call a formatter directly without going through the agent loop's
    set_current_question, and existing tests asserting a specific
    source/positional order, are unaffected.

    `bonus_fn` (mandat "method name tracking", todo/contexte.txt section
    972 item 1 / decision post-975): optional callable returning a numeric
    score to ADD on top of the generic fuzzy-text `_relevance_score` for a
    given item -- lets a caller fold in a deterministic, non-heuristic-text
    signal (e.g. the question's action verb matching the item's real
    enclosing method name) without that caller having to re-implement
    reranking itself. None (the default) preserves the exact prior
    behavior for every existing call site that does not pass it."""
    if not question:
        return items
    if bonus_fn is None:
        return sorted(items, key=lambda item: _relevance_score(text_fn(item), question), reverse=True)
    return sorted(
        items,
        key=lambda item: _relevance_score(text_fn(item), question) + bonus_fn(item),
        reverse=True,
    )


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
    order = sorted(
        range(len(sizes)),
        key=lambda i: (priority[i] if priority else 0),
        reverse=True,
    )
    if protected_total > budget:
        alloc = [0] * len(sizes)
        remaining = budget
        for i in order:
            if protected[i] and protected[i] <= remaining:
                alloc[i] = protected[i]
                remaining -= protected[i]
        return alloc

    alloc = [p for p in protected]
    remaining = budget - protected_total

    # Atomic items (protected == 0 -- a single line, no internal newline
    # for _truncate_observation to rewind to) are all-or-nothing: granted
    # their FULL size, in priority order, while it still fits. A tiny
    # partial share is worse than useless here -- with no newline to cut
    # back to, _truncate_observation hard-cuts mid-line and still appends
    # its truncation marker, so the actual output can end up LONGER than
    # the tiny cap it was given, and even without that overshoot, half a
    # line is just noise.
    for i in order:
        if protected[i] == 0 and sizes[i] <= remaining:
            alloc[i] = sizes[i]
            remaining -= sizes[i]

    # Flexible items (protected > 0 -- multi-line, safe to cut back to
    # their protected prefix) water-fill whatever budget remains among
    # themselves, independently of the atomic items' all-or-nothing grants
    # above.
    flex_indices = [i for i, p in enumerate(protected) if p > 0]
    if flex_indices:
        extra_sizes = [sizes[i] - alloc[i] for i in flex_indices]
        extra_alloc = waterfill_budget(extra_sizes, remaining)
        for idx, e in zip(flex_indices, extra_alloc):
            alloc[idx] += e

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
