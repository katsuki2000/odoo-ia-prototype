"""
Section 977 (todo/contexte.txt), cause B: PUR-Q5's essential-tier commande
volet is correct, but the exception-tier messages for the SAME native
purchase_order.py block (`_unlink_if_cancelled`, `button_cancel`) are cut
in full -- not merely truncated -- because `purchase.order` has an
unusually wide fan-out (6 contributing files this turn) whose combined
essential portions alone already exceed the tool's budget. The pre-existing
two-tier water-filling (837) only guarantees a protected minimum WITHIN
each tier; nothing stopped the essential tier from claiming the entire
budget and leaving literally 0 chars for tier 2, even when a block's own
exception messages would easily fit if only tier 2 got any budget at all.

This reproduces that shape directly against `assemble_security_lock_blocks`
(no LLM, no real analyze_security_locks call) with synthetic blocks sized so
that, under the OLD single-pool-then-leftover split, the essential tier
alone would exhaust the budget -- and asserts the exception tier now always
gets at least its protected floor.
"""

from code_intelligence.rules.security_evidence import (
    assemble_security_lock_blocks,
    _EXCEPTION_MESSAGES_MARKER,
)


def _block(header: str, n_filler_lines: int, exception_message: str | None) -> str:
    """A synthetic per-file block: header + filler essential lines, plus an
    optional exception-messages section (mirrors format_security_locks_summary's
    real shape closely enough for assemble_security_lock_blocks's own split
    logic, which only looks for _EXCEPTION_MESSAGES_MARKER)."""
    lines = [header] + [f"  - filler finding line #{i} with some real content" for i in range(n_filler_lines)]
    text = "\n".join(lines)
    if exception_message is not None:
        text += f"\n{_EXCEPTION_MESSAGES_MARKER} (UserError/ValidationError):\n  - {exception_message}"
    return text


def test_essential_tier_cannot_fully_starve_exception_tier_of_a_fitting_message():
    # 5 "other contributing files" blocks, each with a hefty essential
    # portion and no exception messages of their own (mirrors the OCA/
    # mail-mixin/populate contributors in the real PUR-Q5 fan-out -- present,
    # but not what the question is actually about).
    filler_blocks = [
        _block(f"Analyse des verrous Python (contrib_{i}.py):", n_filler_lines=8, exception_message=None)
        for i in range(5)
    ]
    # The one block that matters: a compact essential portion (fits easily)
    # plus a short, real exception message that must survive.
    native_block = _block(
        "Analyse des verrous Python (purchase_order.py):",
        n_filler_lines=2,
        exception_message="Unable to cancel this purchase order. You must first cancel the related vendor bills.",
    )
    blocks = filler_blocks + [native_block]

    # Budget deliberately set so the summed essential portions of the 5
    # filler blocks alone already exceed it -- under the OLD behavior
    # (essential_budget = min(budget, sum(essential_sizes))) the entire
    # budget is claimed by tier 1, leaving remaining_budget == 0 for tier 2
    # no matter how short the native block's own exception message is.
    total_essential = sum(len(b.split(_EXCEPTION_MESSAGES_MARKER)[0]) for b in blocks)
    budget = total_essential - 50  # tight enough to force real competition

    result = assemble_security_lock_blocks(blocks, budget)

    assert "purchase_order.py" in result
    assert "Unable to cancel this purchase order" in result, (
        "the native block's exception message must get SOME budget even "
        "when other blocks' essential portions alone could exhaust the "
        "total -- this was silently 0 before the section 977 fix"
    )


def test_no_regression_when_there_is_no_meaningful_exception_tier():
    # All-essential blocks, no exception markers anywhere -- exception_floor
    # must come out to 0 and the essential tier must behave exactly as
    # before (this is the overwhelmingly common case; the fix must be a
    # no-op here).
    blocks = [
        _block(f"Analyse des verrous Python (f_{i}.py):", n_filler_lines=6, exception_message=None)
        for i in range(4)
    ]
    total_essential = sum(len(b) for b in blocks)
    budget = total_essential - 30

    result = assemble_security_lock_blocks(blocks, budget)
    assert len(result) <= budget + 4 * len("[... Content truncated ...]")  # generous slack for truncation markers
    assert "f_0.py" in result  # at least the protected-minimum guarantee (837) still holds


def test_short_exception_message_fits_whole_even_under_tight_budget():
    # A single block whose exception message is short enough that its
    # protected floor is trivially small -- confirms exception_floor does
    # not over-reserve and starve the essential tier for no reason.
    block = _block(
        "Analyse des verrous Python (small.py):",
        n_filler_lines=1,
        exception_message="Cannot delete.",
    )
    result = assemble_security_lock_blocks([block], budget=len(block))
    assert result == block
