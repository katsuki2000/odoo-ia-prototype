from odoo import models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_valider_avoir(self):
        for rec in self:
            if rec.partner_id.avoir_vip_exempt:
                # client VIP : validation directe, pas de seuil
                rec.avoir_valide_par_id = self.env.user
                rec.avoir_niveau_appro = 'n1'
                continue
        return super().action_valider_avoir()
