from odoo import models, fields, api
from odoo.exceptions import ValidationError


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    conge_urgence = fields.Boolean(string="Demande urgente")

    @api.constrains('number_of_days', 'employee_id')
    def _check_solde_conge(self):
        for rec in self:
            solde = rec.employee_id.remaining_leaves
            if rec.number_of_days > solde and not rec.conge_urgence:
                raise ValidationError(
                    "Impossible de valider : le solde de conges restant (%.1f jours) est insuffisant. "
                    "Cochez 'Demande urgente' pour soumettre quand meme a validation exceptionnelle du N+2." % solde
                )

    def action_approve(self):
        for rec in self:
            if rec.conge_urgence and rec.number_of_days > rec.employee_id.remaining_leaves:
                n2 = rec.employee_id.parent_id.parent_id.user_id
                if self.env.user != n2 and not self.env.user.has_group('hr_holidays.group_hr_holidays_manager'):
                    raise ValidationError(
                        "Une demande urgente depassant le solde doit etre validee par le N+2 ou un responsable RH."
                    )
        return super().action_approve()
