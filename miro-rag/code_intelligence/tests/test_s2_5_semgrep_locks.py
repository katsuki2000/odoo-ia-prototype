"""
code_intelligence/tests/test_s2_5_semgrep_locks.py

Unit tests for Stories S2.5 & S2.6:
  - S2.5: Detection of hardcoded email/login lock lists (_VALIDATEURS_EXCEPTIONNELS) and ValidationError/UserError messages.
  - S2.6: Detection of dynamic uncertainties (getattr, eval, exec) with low confidence tagging.
  Validates adversarial tests Q3.1, Q2.1, and Q9.1.
"""

import pytest
import textwrap
from pathlib import Path
from code_intelligence.semgrep_locks_analyzer import (
    analyze_python_security_locks,
    PythonSecurityLockAnalysis,
)


class TestHardcodedLockDetection:
    def test_detects_hardcoded_email_lists_q3_1(self):
        """Test Q3.1: Detection of _VALIDATEURS_EXCEPTIONNELS with hardcoded emails."""
        code = textwrap.dedent("""\
            from odoo import models, fields
            from odoo.exceptions import UserError

            class CustomPurchaseRequest(models.Model):
                _name = 'custom.purchase.request'
                _VALIDATEURS_EXCEPTIONNELS = ['direction@societe.com', 'daf@societe.com']

                def action_valider(self):
                    email_ok = self.env.user.login in self._VALIDATEURS_EXCEPTIONNELS
                    if not email_ok:
                        raise UserError("Vous n'avez pas le droit de valider cette demande d'achat.")
        """)
        analysis = analyze_python_security_locks(code, "custom_purchase_request/models/purchase_request.py")
        assert analysis.has_hardcoded_logins is True
        assert "direction@societe.com" in analysis.hardcoded_logins
        assert "daf@societe.com" in analysis.hardcoded_logins
        assert len(analysis.exception_messages) >= 1
        assert "Vous n'avez pas le droit de valider cette demande d'achat." in analysis.exception_messages[0]

    def test_detects_has_group_required_group_bloc9_01a(self):
        """Bloc 9 gap (2026-08-10, bloc9-01a-business): a has_group() guard's
        technical group xmlid must be extracted, not only the UserError
        message text -- a governance question needs the citable identifier,
        not only the human-readable sentence."""
        code = textwrap.dedent("""\
            from odoo import models, fields
            from odoo.exceptions import UserError

            class AccountMove(models.Model):
                _inherit = 'account.move'

                def action_valider_avoir(self):
                    for rec in self:
                        if rec.amount_total > 5000 and not self.env.user.has_group('account.group_account_manager'):
                            raise UserError("Seul un responsable comptable peut valider un avoir de plus de 5000e.")
        """)
        analysis = analyze_python_security_locks(code, "custom_credit_note_approval/models/account_move.py")
        assert "account.group_account_manager" in analysis.required_groups
        assert "account.group_account_manager" in analysis.summary_text

    def test_no_has_group_call_leaves_required_groups_empty(self):
        code = textwrap.dedent("""\
            from odoo import models
            from odoo.exceptions import UserError

            class Simple(models.Model):
                _name = 'simple.model'

                def action_x(self):
                    raise UserError("Non autorise.")
        """)
        analysis = analyze_python_security_locks(code, "simple.py")
        assert analysis.required_groups == []

    def test_captures_nested_if_condition_for_raise_bloc9_05c(self):
        """Bloc 9 gap (module 5/8, custom_asset_loan, 2026-08-10,
        bloc9-05c-no-link-trap): a raise guarded by nested `if`s must carry
        its enclosing condition(s) alongside the message, outer to inner --
        otherwise the rule reads as unconditional and a "does this still
        apply with no linked purchase request?" question gets answered
        "yes, regardless of amount", the exact inverse of the ground truth
        (the whole condition short-circuits to False with nothing linked).
        Mirrors the real custom_asset_loan/models/asset_loan.py source
        verbatim (two nested ifs: demande_achat_liee_id set AND its
        montant_estime > 2000, then a second if for the actual role clash)."""
        code = textwrap.dedent("""\
            from odoo import models, fields, api
            from odoo.exceptions import UserError


            class CustomAssetLoan(models.Model):
                _name = 'custom.asset.loan'

                def action_demarrer(self):
                    for rec in self:
                        if rec.demande_achat_liee_id and rec.demande_achat_liee_id.montant_estime > 2000:
                            if rec.demande_achat_liee_id.demandeur_id == rec.beneficiaire_id:
                                raise UserError(
                                    "Separation des roles requise : le beneficiaire d'un materiel de plus "
                                    "de 2000 euros doit etre different du demandeur initial."
                                )
                        rec.etat = 'en_cours'
        """)
        analysis = analyze_python_security_locks(code, "custom_asset_loan/models/asset_loan.py")
        assert len(analysis.exception_messages) == 1
        assert len(analysis.exception_conditions) == 1
        condition = analysis.exception_conditions[0]
        # Both the outer (link + threshold) and inner (role clash) tests
        # must be present -- the outer one is what module 5/8's trap
        # question actually hinges on.
        assert "demande_achat_liee_id" in condition
        assert "2000" in condition
        assert "demandeur_id" in condition
        assert "condition :" in analysis.summary_text
        assert "demande_achat_liee_id" in analysis.summary_text

    def test_no_enclosing_if_leaves_condition_empty(self):
        """Symmetric negative case: a raise with no enclosing `if` at all
        must report an empty condition, not a stale/leaked one from a
        sibling branch -- same convention as required_groups' empty-list
        case above."""
        code = textwrap.dedent("""\
            from odoo import models
            from odoo.exceptions import UserError

            class Simple(models.Model):
                _name = 'simple.model'

                def action_x(self):
                    raise UserError("Non autorise.")
        """)
        analysis = analyze_python_security_locks(code, "simple.py")
        assert analysis.exception_conditions == [""]
        assert "condition :" not in analysis.summary_text

    def test_link_guard_field_detected_on_real_asset_loan_shape_bloc9_05c(self):
        """Bloc 9 gap, part 2 (module 5/8, 2026-08-10, bloc9-05c-no-link-trap):
        beyond capturing the raw condition text (previous test), the
        analyzer must also detect the specific short-circuit-guard SHAPE --
        a bare truthiness check on a relational field as the first `and`
        operand -- and surface it as a computed field name, since a live
        run showed the synthesis LLM misreading the short-circuit direction
        even with the raw condition text quoted to it verbatim. Same
        source shape as the real asset_loan.py module."""
        code = textwrap.dedent("""\
            from odoo import models, fields, api
            from odoo.exceptions import UserError


            class CustomAssetLoan(models.Model):
                _name = 'custom.asset.loan'

                def action_demarrer(self):
                    for rec in self:
                        if rec.demande_achat_liee_id and rec.demande_achat_liee_id.montant_estime > 2000:
                            if rec.demande_achat_liee_id.demandeur_id == rec.beneficiaire_id:
                                raise UserError(
                                    "Separation des roles requise : le beneficiaire d'un materiel de plus "
                                    "de 2000 euros doit etre different du demandeur initial."
                                )
                        rec.etat = 'en_cours'
        """)
        analysis = analyze_python_security_locks(code, "custom_asset_loan/models/asset_loan.py")
        assert len(analysis.exception_guard_fields) == 1
        assert analysis.exception_guard_fields[0] == "rec.demande_achat_liee_id"
        assert "[GARDE DE LIEN:" in analysis.summary_text
        assert "court-circuit" in analysis.summary_text
        assert "NE S'APPLIQUE PAS" in analysis.summary_text

    def test_link_guard_field_empty_when_condition_is_pure_numeric_compare(self):
        """Negative case: a condition that is ONLY a numeric/value comparison
        (`rec.amount_total > 2000`, no relational-field truthiness check
        anywhere) is not a link guard -- there is no falsy-relational-field
        interpretation to warn about, so no [GARDE DE LIEN] annotation
        should be produced (a false positive here would be actively
        misleading, worse than saying nothing)."""
        code = textwrap.dedent("""\
            from odoo import models
            from odoo.exceptions import UserError

            class Simple(models.Model):
                _name = 'simple.model'

                def action_x(self):
                    for rec in self:
                        if rec.amount_total > 2000:
                            raise UserError("Montant trop eleve.")
        """)
        analysis = analyze_python_security_locks(code, "simple.py")
        assert analysis.exception_guard_fields == [""]
        assert "[GARDE DE LIEN:" not in analysis.summary_text

    def test_link_guard_field_detected_on_bare_truthiness_without_and(self):
        """A bare `if rec.linked_id:` with no `and` at all is still a link
        guard (the whole condition IS the truthiness check) -- must not
        require the two-operand `and` shape specifically."""
        code = textwrap.dedent("""\
            from odoo import models
            from odoo.exceptions import UserError

            class Simple(models.Model):
                _name = 'simple.model'

                def action_x(self):
                    for rec in self:
                        if rec.linked_id:
                            raise UserError("Bloque car lie.")
        """)
        analysis = analyze_python_security_locks(code, "simple.py")
        assert analysis.exception_guard_fields == ["rec.linked_id"]
        assert "[GARDE DE LIEN:" in analysis.summary_text

    def test_link_guard_field_not_fabricated_for_boolean_auth_check_bloc9_05c_rerun(self):
        """Bloc 9 gap, module 5/8 fix rerun (2026-08-11, cross-module
        contamination on bloc9-05c-no-link-trap): a live run on a question
        mentioning both custom_asset_loan AND custom_purchase_request
        (legitimately, since asset_loan links to a purchase request) showed
        a fabricated "[GARDE DE LIEN: si 'not (user_ok or email_ok)'..."
        annotation on custom_purchase_request's own, unrelated first gate --
        a boolean authorization check, not a relational-field presence
        check, so it can never be "vide/absent" the way a Many2one field
        can. Root cause: _detect_link_guard_field's second branch matched
        any test that was merely "not a Compare and not a BoolOp", which
        also matches an ast.UnaryOp like `not (a or b)`. Mirrors the real
        custom_purchase_request/models/purchase_request.py source verbatim
        (both raises: the boolean gate, then the amount-and-not-email_ok
        gate) -- neither must ever produce a [GARDE DE LIEN] annotation."""
        code = textwrap.dedent("""\
            from odoo import models, fields, api
            from odoo.exceptions import UserError


            class CustomPurchaseRequest(models.Model):
                _name = 'custom.purchase.request'
                _VALIDATEURS_EXCEPTIONNELS = ['direction@societe.com', 'daf@societe.com']

                def action_valider(self):
                    for rec in self:
                        user_ok = self.env.user.has_group('purchase.group_purchase_manager')
                        email_ok = self.env.user.login in rec._VALIDATEURS_EXCEPTIONNELS
                        if not (user_ok or email_ok):
                            raise UserError("Vous n'avez pas le droit de valider cette demande d'achat.")
                        if rec.montant_estime > 10000 and not email_ok:
                            raise UserError("Au-dela de 10 000 euros, seule la Direction peut valider (liste restreinte).")
        """)
        analysis = analyze_python_security_locks(code, "custom_purchase_request/models/purchase_request.py")
        assert len(analysis.exception_messages) == 2
        # The actual bug: no fabricated link-guard field/annotation for a
        # boolean authorization check.
        assert analysis.exception_guard_fields == ["", ""]
        assert "[GARDE DE LIEN:" not in analysis.summary_text
        # NOTE (2026-08-11, first real pytest run of this test): an earlier
        # version of this test also asserted "user_ok"/"email_ok" not in
        # analysis.summary_text -- wrong, and not what this test is about.
        # exception_conditions (a separate, correct, pre-existing feature
        # from module 1/8's original fix, section 14) legitimately renders
        # the raw condition text verbatim, e.g. "condition : not (user_ok
        # or email_ok)" -- that's honest, non-fabricated output, not the
        # bug this test guards against. Removed those two assertions;
        # the two above are the real regression guard.

    def test_detects_validation_error_messages_q2_1(self):
        """Test Q2.1: Extraction of exact ValidationError exception messages."""
        code = textwrap.dedent("""\
            from odoo import models
            from odoo.exceptions import ValidationError

            class HrLeave(models.Model):
                _inherit = 'hr.leave'

                def _check_solde_conge(self):
                    if True:
                        raise ValidationError("Impossible de valider : le solde de conges restant est insuffisant.")
        """)
        analysis = analyze_python_security_locks(code, "custom_hr_leave_workflow/models/hr_leave.py")
        assert len(analysis.exception_messages) == 1
        assert "Impossible de valider : le solde de conges restant est insuffisant." in analysis.exception_messages[0]


class TestDynamicDispatchDetection:
    def test_detects_getattr_dispatch_q9_1(self):
        """Test Q9.1: Detection of getattr dynamic dispatch driving business logic."""
        code = textwrap.dedent("""\
            from odoo import models

            class CustomReimbursementRequest(models.Model):
                _name = 'custom.reimbursement.request'

                def action_valider(self):
                    f = getattr(self, '_g_%s' % self.env['ir.config_parameter'].sudo().get_param('custom_reimb.mode'), None)
                    v = f() if f else False
        """)
        analysis = analyze_python_security_locks(code, "custom_expense_reimbursement_indirect/models/reimbursement.py")
        assert analysis.has_dynamic_dispatch is True
        assert "getattr" in analysis.dynamic_dispatch_types
        assert "file://" in analysis.summary_text
        assert "#L1-" in analysis.summary_text
        assert analysis.confidence == "low"
        assert len(analysis.security_warnings) >= 1
        assert "DISPATCH DYNAMIQUE" in analysis.security_warnings[0]

    def test_header_confidence_label_is_french_faible_not_english_low_bloc9_07(self):
        """Bloc 9 gap, module 7/8 (2026-08-10, bloc9-07 raw check): the
        per-analysis header line ("Analyse des verrous Python (...)
        [Confiance: ...]") used to render the STORED confidence value
        ('low', English) via a raw .upper(), producing the inconsistent
        "[Confiance: LOW]" -- every other low-confidence message in this
        codebase (the inline DISPATCH DYNAMIQUE warning right below it,
        the override-chain warnings, etc.) says "[Confiance: FAIBLE]" in
        French. `analysis.confidence` itself must stay the English 'low'
        string (asserted right above, other code may rely on it) -- only
        the rendered header label changes."""
        code = textwrap.dedent("""\
            from odoo import models

            class CustomReimbursementRequest(models.Model):
                _name = 'custom.reimbursement.request'

                def action_valider(self):
                    f = getattr(self, '_g_%s' % self.env['ir.config_parameter'].sudo().get_param('custom_reimb.mode'), None)
                    v = f() if f else False
        """)
        analysis = analyze_python_security_locks(code, "custom_expense_reimbursement_indirect/models/reimbursement.py")
        assert analysis.confidence == "low"
        assert "[Confiance: FAIBLE]" in analysis.summary_text
        assert "[Confiance: LOW]" not in analysis.summary_text

    def test_clean_code(self):
        """Test clean code without security locks or dynamic dispatches."""
        code = textwrap.dedent("""\
            from odoo import models, fields

            class SimpleModel(models.Model):
                _name = 'simple.model'
                name = fields.Char()
        """)
        analysis = analyze_python_security_locks(code, "simple.py")
        assert analysis.has_hardcoded_logins is False
        assert analysis.has_dynamic_dispatch is False
        assert analysis.exception_messages == []
        assert analysis.confidence == "high"
