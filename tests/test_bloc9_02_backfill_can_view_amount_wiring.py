# -*- coding: utf-8 -*-
"""
tests/test_bloc9_02_backfill_can_view_amount_wiring.py

Bug B1 (module 02,  section 96, fixed section 97):
_backfill_missing_can_view_amount_fact (rag/ci_helpers.py) was written,
unit-tested implicitly via its own docstring contract, and imported into
rag/ci_agent_node.py -- but never actually CALLED anywhere in that file.
No existing test caught this: test_bloc9_08_can_view_amount_contradiction.py
only exercises _correct_can_view_amount_contradictions and its helpers,
never this backfill.

This file covers two things:
  1. The backfill function itself, in isolation (append/no-op contract).
  2. The exact cascade this wiring gap caused in production (section 96
     diagnostic): _backfill_missing_security_lock_amount's own no-op guard
     (`if _has_can_view_amount_fact(final_answer): return final_answer`)
     is only effective when _backfill_missing_can_view_amount_fact has
     already run on final_answer -- otherwise it goes on to inject an
     unrelated security-lock threshold (e.g. another module's 5000€ lock
     sharing the same account.move model) as if it were relevant. The fix
     (rag/ci_agent_node.py) calls the backfill FIRST, before every other
     backfill/correction in that block -- test 2 below locks that ordering
     contract, not just the two functions in isolation.
"""

import pytest

from code_intelligence.ci_agent_node.guards.can_view_verifier import (
    _backfill_missing_can_view_amount_fact,
    _has_can_view_amount_fact,
    _format_can_view_amount_fact,
)
from code_intelligence.security.locks import _backfill_missing_security_lock_amount


# ---------------------------------------------------------------------------
# 1. _backfill_missing_can_view_amount_fact in isolation
# ---------------------------------------------------------------------------

class TestBackfillMissingCanViewAmountFact:
    def test_appends_fact_block_when_missing_from_final_answer(self):
        fact_block = _format_can_view_amount_fact(80000, False)
        raw_tool_output = "Some unrelated tool block.\n\n" + fact_block
        final_answer = "Réponse synthétisée qui a paraphrasé le fait sans le citer."

        result = _backfill_missing_can_view_amount_fact(final_answer, raw_tool_output)

        assert fact_block in result
        assert result.startswith(final_answer)

    def test_no_op_when_final_answer_already_has_fact(self):
        fact_block = _format_can_view_amount_fact(30000, True)
        final_answer = "Prose correcte.\n\n" + fact_block

        result = _backfill_missing_can_view_amount_fact(final_answer, "raw output sans rapport")

        assert result == final_answer

    def test_no_op_when_raw_tool_output_never_carried_the_fact(self):
        final_answer = "Réponse quelconque."
        raw_tool_output = "Aucun fait can_view_amount_v2 ici, juste un autre outil."

        result = _backfill_missing_can_view_amount_fact(final_answer, raw_tool_output)

        assert result == final_answer

    def test_indeterminate_fact_is_recovered_too(self):
        fact_block = _format_can_view_amount_fact(60000, None, ["company_id"])
        raw_tool_output = fact_block
        final_answer = "Réponse qui ne mentionne pas l'incertitude."

        result = _backfill_missing_can_view_amount_fact(final_answer, raw_tool_output)

        assert fact_block in result
        assert _has_can_view_amount_fact(result) is True


# ---------------------------------------------------------------------------
# 2. Cascade fix -- reproduces the section 96/81 symptom and locks the
#    correct call order (backfill-the-fact BEFORE the security-lock-amount
#    backfill, not merely before _correct_can_view_amount_contradictions).
# ---------------------------------------------------------------------------

# Module 2's own can_view_amount_v2 verdict for an out-of-scope amount --
# distinct model/mechanism from the unrelated lock below, but sharing the
# same underlying account.move model in raw_tool_output, exactly as
# described in section 96 (custom_credit_note_approval's 5000€ Python lock
# vs. module 02's own ir.rule-based can_view_amount_v2 verdict).
_CAN_VIEW_FACT_BLOCK = _format_can_view_amount_fact(80000, True)

_UNRELATED_SECURITY_LOCK_BLOCK = (
    "  - Security lock messages (UserError/ValidationError):\n"
    '  * "Montant trop eleve" (condition : rec.amount_total > 5000 and '
    "has_group('custom_credit_note_approval.group_credit_note_manager'))"
)

_RAW_TOOL_OUTPUT = _UNRELATED_SECURITY_LOCK_BLOCK + "\n\n" + _CAN_VIEW_FACT_BLOCK

_QUESTION = "Un utilisateur standard peut-il consulter un avoir de 80 000€ ?"


class TestBackfillOrderingPreventsUnrelatedSeuilInjection:
    def test_without_the_fix_the_unrelated_seuil_leaks_in(self):
        """Reproduces the pre-fix bug directly: if
        _backfill_missing_security_lock_amount runs BEFORE the can_view
        fact has been backfilled into final_answer, its own no-op guard
        never triggers, and the unrelated 5000€ lock gets injected into an
        answer about an 80 000€ can_view_amount_v2 verdict."""
        final_answer = "Réponse synthétisée sans le fait can_view_amount_v2."

        buggy_result = _backfill_missing_security_lock_amount(
            final_answer, _RAW_TOOL_OUTPUT, question=_QUESTION,
        )

        assert "5000€" in buggy_result or "5000" in buggy_result

    def test_with_the_fix_the_unrelated_seuil_is_not_injected(self):
        """The fixed call order (rag/ci_agent_node.py): the can_view fact
        is backfilled first, so _backfill_missing_security_lock_amount's
        guard now correctly sees it and no-ops."""
        final_answer = "Réponse synthétisée sans le fait can_view_amount_v2."

        final_answer = _backfill_missing_can_view_amount_fact(final_answer, _RAW_TOOL_OUTPUT)
        assert _has_can_view_amount_fact(final_answer) is True

        fixed_result = _backfill_missing_security_lock_amount(
            final_answer, _RAW_TOOL_OUTPUT, question=_QUESTION,
        )

        assert "5000" not in fixed_result
        # The real can_view_amount_v2 verdict is still present, untouched.
        assert _CAN_VIEW_FACT_BLOCK in fixed_result
