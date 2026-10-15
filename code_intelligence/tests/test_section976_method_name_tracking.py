"""
code_intelligence/tests/test_section976_method_name_tracking.py

Mandat "method name tracking" (todo/contexte.txt section 972 item 1,
mandat donne post-975): the enclosing method's real name is now captured
alongside each exception_message in SecurityLockASTVisitor
(security.py), threaded through PythonSecurityLockAnalysis /
build_security_lock_evidence / format_security_locks_summary, and used as
a deterministic relevance-reranking bonus (_method_family_bonus,
security_evidence.py) so a question's action verb (e.g. "supprimer") can
be matched to the real Odoo method family (e.g. "unlink") instead of
relying purely on fuzzy whole-sentence text similarity.

Reproduces the concrete PUR-Q5 scenario from section 972's diagnosis: the
real deletion message (_unlink_if_cancelled, "In order to delete a
purchase order, you must cancel it first.") scored 36.1 under
_relevance_score alone, BEHIND two unrelated messages scoring 42.8/39.1
("There is no invoiceable line...", "Unable to cancel this purchase
order... vendor bills") -- structurally unable to survive the tight
exception-tier budget. The tests below assert this is now fixed.
"""

import ast

from code_intelligence.rules.security import SecurityLockASTVisitor, analyze_python_security_locks
from code_intelligence.rules.security_evidence import (
    build_security_lock_evidence,
    format_security_locks_summary,
    _method_family_bonus,
)
from code_intelligence.rules.relevance_budget import _rerank_by_relevance
from code_intelligence.agent.tool_helpers import set_current_question


_PUR_Q5_CODE = '''
class PurchaseOrder(models.Model):
    _name = "purchase.order"

    @api.ondelete(at_uninstall=False)
    def _unlink_if_cancelled(self):
        for order in self:
            if not order.state == 'cancel':
                raise UserError(_('In order to delete a purchase order, you must cancel it first.'))

    def action_create_invoice(self):
        if not self.order_line:
            raise UserError(_('There is no invoiceable line.'))

    def button_cancel(self):
        for inv in self.invoice_ids:
            if inv.state not in ('cancel', 'draft'):
                raise UserError(_('Unable to cancel this purchase order. You must first cancel the related vendor bills.'))
'''


class TestASTVisitorCapturesExceptionMethod:
    def test_exception_methods_mirrors_exception_messages_length(self):
        tree = ast.parse(_PUR_Q5_CODE)
        visitor = SecurityLockASTVisitor("purchase_order.py")
        visitor.visit(tree)
        assert len(visitor.exception_methods) == len(visitor.exception_messages) == 3

    def test_exception_methods_captures_real_enclosing_method_names(self):
        tree = ast.parse(_PUR_Q5_CODE)
        visitor = SecurityLockASTVisitor("purchase_order.py")
        visitor.visit(tree)
        by_method = dict(zip(visitor.exception_messages, visitor.exception_methods))
        assert by_method["In order to delete a purchase order, you must cancel it first."] == "_unlink_if_cancelled"
        assert by_method["There is no invoiceable line."] == "action_create_invoice"
        assert by_method["Unable to cancel this purchase order. You must first cancel the related vendor bills."] == "button_cancel"

    def test_regex_fallback_leaves_exception_methods_empty_not_misaligned(self):
        # No AST/control-flow info in the regex fallback path -- must stay ""
        # (never a guess), same discipline as required_group_methods' own
        # regex-fallback branch, but list length must still track messages.
        result = analyze_python_security_locks("this is not : valid python (((", "broken.py")
        assert len(result.exception_methods) == len(result.exception_messages)


class TestBuildSecurityLockEvidenceIncludesMethod:
    def test_claim_mentions_method_name_when_present(self):
        evidence = build_security_lock_evidence(
            filepath="purchase_order.py",
            hardcoded_logins=[],
            exception_messages=["In order to delete a purchase order, you must cancel it first."],
            exception_conditions=["not order.state == 'cancel'"],
            exception_guard_fields=[""],
            exception_linenos=[10],
            required_groups=[],
            required_group_methods=[],
            required_group_linenos=[],
            dynamic_dispatch_types=[],
            exception_methods=["_unlink_if_cancelled"],
        )
        exc_evidence = [e for e in evidence if "delete a purchase order" in e.claim]
        assert exc_evidence and "_unlink_if_cancelled" in exc_evidence[0].claim

    def test_no_crash_and_no_method_mention_when_exception_methods_omitted(self):
        # Optional param, defaults to None -- every pre-976 caller that never
        # passes it must keep working unchanged.
        evidence = build_security_lock_evidence(
            filepath="x.py",
            hardcoded_logins=[],
            exception_messages=["Some error."],
            exception_conditions=[""],
            exception_guard_fields=[""],
            exception_linenos=[5],
            required_groups=[],
            required_group_methods=[],
            required_group_linenos=[],
            dynamic_dispatch_types=[],
        )
        exc_evidence = [e for e in evidence if "Some error" in e.claim]
        assert exc_evidence and "in method" not in exc_evidence[0].claim


class TestMethodFamilyBonus:
    def test_matching_family_and_question_gives_bonus(self):
        assert _method_family_bonus("_unlink_if_cancelled", "Quelles regles empechent de supprimer une commande") == 100.0

    def test_no_bonus_when_question_has_no_matching_verb(self):
        assert _method_family_bonus("_unlink_if_cancelled", "Quel est le montant total ?") == 0.0

    def test_no_bonus_when_method_name_empty(self):
        assert _method_family_bonus("", "supprimer une commande") == 0.0

    def test_no_bonus_when_question_missing(self):
        assert _method_family_bonus("_unlink_if_cancelled", None) == 0.0

    def test_cancel_family_matches_button_cancel(self):
        assert _method_family_bonus("button_cancel", "peut-on annuler cette commande ?") == 100.0

    def test_unrelated_family_present_in_method_name_no_match(self):
        # "button_cancel" does not contain "unlink" -- a "supprimer" question
        # must not get a spurious bonus from an unrelated family substring.
        assert _method_family_bonus("button_cancel", "supprimer la commande") == 0.0


class TestRerankByRelevanceBonusFn:
    def test_bonus_fn_none_preserves_prior_behavior(self):
        items = [("b text", 1), ("a text matching question", 2)]
        result = _rerank_by_relevance(items, text_fn=lambda i: i[0], question="matching question")
        assert result[0][1] == 2

    def test_bonus_fn_can_override_fuzzy_ranking(self):
        # "b" alone scores low on fuzzy text, but a decisive bonus must still
        # push it above "a" which has no bonus.
        items = [("a text matching question strongly", 1), ("b", 2)]
        result = _rerank_by_relevance(
            items,
            text_fn=lambda i: i[0],
            question="matching question",
            bonus_fn=lambda i: 1000.0 if i[1] == 2 else 0.0,
        )
        assert result[0][1] == 2

    def test_bonus_fn_noop_without_question_matches_old_signature(self):
        items = [("x", 1), ("y", 2)]
        result = _rerank_by_relevance(items, text_fn=lambda i: i[0], question=None, bonus_fn=lambda i: 999)
        assert result == items


class TestPurQ5EndToEndReranking:
    """Direct reproduction of the section 972 diagnosis: format the 3
    real exception messages from purchase_order.py, ask the exact PUR-Q5
    question, and assert the deletion message now ranks FIRST (it was
    3rd/5 -- here 3rd/3 -- under fuzzy scoring alone per section 972)."""

    def test_deletion_message_ranks_first_for_pur_q5_question(self):
        set_current_question(
            "Quelles regles empechent de supprimer une commande d'achat ou "
            "une de ses lignes selon leur etat, et quelle contrainte SQL "
            "distincte s'applique sur les lignes elles-memes ?"
        )
        try:
            result = analyze_python_security_locks(_PUR_Q5_CODE, "purchase_order.py")
            summary = format_security_locks_summary(result, _PUR_Q5_CODE, "purchase_order.py")
        finally:
            set_current_question(None)

        deletion_idx = summary.find("you must cancel it first")
        invoiceable_idx = summary.find("no invoiceable line")
        vendor_bills_idx = summary.find("vendor bills")
        assert deletion_idx != -1 and invoiceable_idx != -1 and vendor_bills_idx != -1
        assert deletion_idx < invoiceable_idx
        assert deletion_idx < vendor_bills_idx
        assert "_unlink_if_cancelled" in summary
