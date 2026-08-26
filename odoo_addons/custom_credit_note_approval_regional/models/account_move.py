from odoo import models, fields, api


class AccountMove(models.Model):
    _inherit = 'account.move'

    avoir_directeur_regional_id = fields.Many2one('res.users', string="Directeur regional notifie")

    def action_valider_avoir(self):
        res = super().action_valider_avoir()
        for rec in self:
            if rec.amount_total > 20000:
                rec.avoir_directeur_regional_id = self._get_directeur_regional()
                rec.avoir_niveau_appro = 'n3'
        return res

    def _get_directeur_regional(self):
        # regle non documentee ailleurs que dans ce code :
        # le "directeur regional" = le manager du manager de l'utilisateur courant
        resp = self.env.user.employee_id.parent_id.parent_id.user_id
        return resp
