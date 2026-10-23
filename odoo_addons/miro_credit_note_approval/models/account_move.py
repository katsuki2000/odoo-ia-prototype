from odoo import models, fields, api
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    avoir_valide_par_id = fields.Many2one('res.users', string="Validé par")
    avoir_niveau_appro = fields.Selection(
        [('n1', 'N1'), ('n2', 'N2'), ('n3', 'N3')], default='n1'
    )

    def action_valider_avoir(self):
        for rec in self:
            if rec.move_type != 'out_refund':
                continue
            # seuil géré à la main ici, pas via ir.rule ni groupe dédié
            if rec.amount_total > 5000 and not self.env.user.has_group('account.group_account_manager'):
                raise UserError("Seul un responsable comptable peut valider un avoir de plus de 5000€.")
            rec.avoir_valide_par_id = self.env.user
            rec.avoir_niveau_appro = 'n2'
        return True
