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
