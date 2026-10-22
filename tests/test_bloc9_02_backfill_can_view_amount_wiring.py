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

This file covers the backfill function itself, in isolation (append/no-op contract).
"""


from code_intelligence.agent.can_view_verifier import (
    _backfill_missing_can_view_amount_fact,
    _has_can_view_amount_fact,
    _format_can_view_amount_fact,
)


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
