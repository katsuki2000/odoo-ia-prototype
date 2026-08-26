from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


class CustomBaseDocument(models.Model):
    _name = "custom.deep.document"
    _description = "Deep Inheritance Document Base"

    name = fields.Char(string="Name", required=True)
    amount = fields.Float(string="Amount", default=0.0)
    state = fields.Selection([
        ("draft", "Draft"),
        ("level1", "Level 1 Approved"),
        ("level2", "Level 2 Approved"),
        ("validated", "Validated"),
    ], default="draft")
    company_id = fields.Many2one("res.company", string="Company", default=lambda self: self.env.company)
    user_id = fields.Many2one("res.users", string="User", default=lambda self: self.env.user)
    computed_risk_score = fields.Integer(string="Risk Score", compute="_compute_risk_score", store=True)

    @api.depends("amount")
    def _compute_risk_score(self):
        for rec in self:
            rec.computed_risk_score = int(rec.amount / 1000)


class CustomLevel2Document(models.Model):
    _inherit = "custom.deep.document"

    level2_notes = fields.Text(string="Level 2 Notes")

    def action_validate_level2(self):
        for rec in self:
            if rec.amount > 50000 and not self.env.user.has_group("account.group_account_manager"):
                raise UserError("Seul un responsable comptabilité peut valider au-delà de 50 000€.")
            rec.state = "level2"


class CustomLevel3Document(models.Model):
    _inherit = "custom.deep.document"

    level3_flag = fields.Boolean(string="Level 3 Flag")


class CustomLevel4Document(models.Model):
    _inherit = "custom.deep.document"

    level4_supervisor_id = fields.Many2one("res.users", string="Supervisor")


class CustomLevel5Document(models.Model):
    _inherit = "custom.deep.document"

    final_approval_date = fields.Datetime(string="Final Approval Date")

    def action_final_approve(self):
        for rec in self:
            if rec.amount > 100000 and not self.env.user.has_group("base.group_system"):
                raise ValidationError("Approbation finale > 100k€ réservée à l'administrateur système.")
            rec.state = "validated"
