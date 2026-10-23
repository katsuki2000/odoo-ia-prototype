from odoo import models, fields


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    department_id = fields.Many2one('hr.department', string="Departement")
