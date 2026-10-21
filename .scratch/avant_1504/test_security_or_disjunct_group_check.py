"""
code_intelligence/tests/test_security_or_disjunct_group_check.py

Bloc N1 rejeu, PUR-Q1 (todo/contexte.txt, session "SecurityLockASTVisitor
BoolOp/Or gap"): purchase.order._approval_allowed() is not an `if: raise`
gate -- it is a bare `return (A or B or has_group(...))`. Before this fix,
SecurityLockASTVisitor.visit_Call recorded the has_group()/user_has_groups()
call with required_group_is_gating=True (gating_stack empty -> default True,
since there is no enclosing `if`), which format_security_locks_summary then
rendered as an unqualified "ce groupe est requis" claim. That claim is false
whenever the OTHER disjuncts of the same `or` expression are unrelated to
any group and can independently make the method return True (e.g. the
default `po_double_validation == 'one_step'` company config) -- the LLM
downstream has no way to know the group check is only ONE of several
sufficient paths, because that information never reaches the evidence at
all, truncation or not.

Covers:
  - New `required_group_alt_conditions` field on the AST visitor and on
    PythonSecurityLockAnalysis, aligned index-for-index with
    required_groups (real purchase.order._approval_allowed shape,
    simplified for the test).
  - format_security_locks_summary() surfaces the alternative conditions
    explicitly and says the group is NOT the only path.
  - Regression guards: a normal if/raise gate (no enclosing BoolOp/Or) and
    a plain `A and has_group(...)` (BoolOp/And, not Or) must NOT be flagged
    -- both are genuine, unconditional requirements once the code path is
    reached, so alt_conditions must stay empty for them.
"""

import textwrap

from code_intelligence.rules.security import analyze_python_security_locks


APPROVAL_ALLOWED_SOURCE = textwrap.dedent("""\
    class PurchaseOrder(models.Model):
        _inherit = 'purchase.order'

        def _approval_allowed(self):
            return (
                self.company_id.po_double_validation == 'one_step'
                or (self.company_id.po_double_validation == 'two_step'
                    and self.amount_total < self.company_id.po_double_validation_amount)
                or self.user_has_groups('purchase.group_purchase_manager'))
""")


class TestRequiredGroupAltConditionsExtraction:
    def test_or_disjunct_with_unrelated_alternatives_is_captured(self):
        analysis = analyze_python_security_locks(APPROVAL_ALLOWED_SOURCE, "purchase_order.py")

        assert analysis.required_groups == ["purchase.group_purchase_manager"]
        assert len(analysis.required_group_alt_conditions) == 1
        alt = analysis.required_group_alt_conditions[0]
        assert alt != ""
        assert "one_step" in alt
        assert "two_step" in alt

    def test_summary_text_states_group_is_not_the_only_path(self):
        analysis = analyze_python_security_locks(APPROVAL_ALLOWED_SOURCE, "purchase_order.py")
        assert "N'EST PAS le seul chemin" in analysis.summary_text
        assert "one_step" in analysis.summary_text
        assert "purchase.group_purchase_manager" in analysis.summary_text

    def test_evidence_claim_also_carries_the_alt_condition_note(self):
        analysis = analyze_python_security_locks(APPROVAL_ALLOWED_SOURCE, "purchase_order.py")
        grp_ev = next(
            e for e in analysis.evidence
            if e.source == "security_lock:purchase_order.py:group:purchase.group_purchase_manager"
        )
        assert "not the only sufficient path" in grp_ev.claim.lower()
        assert "one_step" in grp_ev.claim


class TestRequiredGroupAltConditionsRegressionGuards:
    def test_plain_if_raise_gate_has_no_alt_conditions(self):
        """The pre-existing, common if/raise pattern -- no enclosing BoolOp
        at all -- must keep alt_conditions empty, exactly as before this
        change (section 825's is_gating stays the only signal there)."""
        code = textwrap.dedent("""\
            class Model(models.Model):
                def action_post(self):
                    if not self.env.user.has_group('base.group_system'):
                        raise UserError("Acces refuse")
        """)
        analysis = analyze_python_security_locks(code, "gate.py")
        assert analysis.required_groups == ["base.group_system"]
        assert analysis.required_group_alt_conditions == [""]
        assert "N'EST PAS le seul chemin" not in analysis.summary_text

    def test_and_conjunction_has_no_alt_conditions(self):
        """`A and has_group(...)` (BoolOp/And, not Or): the group check is
        still a genuine, unconditional requirement for this branch -- there
        is no alternative path that bypasses it. Must not be flagged."""
        code = textwrap.dedent("""\
            class Model(models.Model):
                def _can_do_it(self):
                    return self.state == 'draft' and self.env.user.has_group('base.group_system')
        """)
        analysis = analyze_python_security_locks(code, "conj.py")
        assert analysis.required_groups == ["base.group_system"]
        assert analysis.required_group_alt_conditions == [""]

    def test_or_between_two_group_checks_has_no_alt_conditions(self):
        """`has_group('a') or has_group('b')`: every other disjunct also
        contains a group check, so neither entry has a group-unrelated
        alternative path -- out of scope for this fix (still two distinct
        required_groups entries, both flagged as gating as before)."""
        code = textwrap.dedent("""\
            class Model(models.Model):
                def _can_do_it(self):
                    return (self.env.user.has_group('base.group_a')
                            or self.env.user.has_group('base.group_b'))
        """)
        analysis = analyze_python_security_locks(code, "twogroups.py")
        assert analysis.required_groups == ["base.group_a", "base.group_b"]
        assert analysis.required_group_alt_conditions == ["", ""]

    def test_regex_fallback_path_has_empty_alt_conditions(self):
        """Unparsable code falls back to regex scanning -- no AST/BoolOp
        information available, so alt_conditions must stay empty rather
        than raise or misalign with required_groups."""
        broken_code = "def action_x(self:\n    if self.env.user.has_group('base.group_system'):\n        pass\n"
        analysis = analyze_python_security_locks(broken_code, "broken.py")
        assert analysis.required_groups == ["base.group_system"]
        assert analysis.required_group_alt_conditions == [""]
