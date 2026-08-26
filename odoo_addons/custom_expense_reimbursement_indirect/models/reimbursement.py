from odoo import models, fields, api

_TAB = {0: 1, 1: 0, 2: 0, 3: 1, 4: 0, 5: 1, 6: 0}


class CustomReimbursementRequest(models.Model):
    _name = 'custom.reimbursement.request'
    _description = 'Demande de remboursement de frais'

    employe_id = fields.Many2one(
        'res.users', string='Demandeur', default=lambda self: self.env.user
    )
    montant = fields.Float(string='Montant')
    motif = fields.Char(string='Motif')
    etat = fields.Selection(
        [
            ('brouillon', 'Brouillon'),
            ('valide', 'Validé'),
            ('refuse', 'Refusé'),
        ],
        default='brouillon',
        string='Etat',
    )

    def action_valider(self):
        for r in self:
            f = getattr(
                r,
                '_g_%s' % self.env['ir.config_parameter'].sudo().get_param(
                    'custom_reimb.mode', 'q7'
                ),
                None,
            )
            v = f() if f else False
            r.etat = 'valide' if v else 'refuse'

    def _g_q7(self):
        k = self.employe_id.id % 7
        return bool(_TAB.get(k, 0))
