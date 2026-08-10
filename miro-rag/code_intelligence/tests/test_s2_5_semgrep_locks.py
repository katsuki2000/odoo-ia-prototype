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
