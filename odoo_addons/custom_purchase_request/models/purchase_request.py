from odoo import models, fields, api
from odoo.exceptions import UserError


class CustomPurchaseRequest(models.Model):
    _name = 'custom.purchase.request'
    _description = "Demande d'achat interne"

    name = fields.Char(default='Nouvelle demande')
    demandeur_id = fields.Many2one('res.users', default=lambda self: self.env.user)
    montant_estime = fields.Float()
    etat = fields.Selection(
        [('brouillon', 'Brouillon'), ('a_valider', 'A valider'),
         ('valide', 'Valide'), ('refuse', 'Refuse')],
        default='brouillon'
    )
    justification = fields.Text()

    # Liste d'exceptions codee en dur - contourne le systeme de groupes Odoo
    _VALIDATEURS_EXCEPTIONNELS = ['direction@societe.com', 'daf@societe.com']

    def action_soumettre(self):
        self.etat = 'a_valider'

    def action_valider(self):
        for rec in self:
            user_ok = self.env.user.has_group('purchase.group_purchase_manager')
            email_ok = self.env.user.login in rec._VALIDATEURS_EXCEPTIONNELS
            if not (user_ok or email_ok):
                raise UserError("Vous n'avez pas le droit de valider cette demande d'achat.")
            if rec.montant_estime > 10000 and not email_ok:
                raise UserError("Au-dela de 10 000 euros, seule la Direction peut valider (liste restreinte).")
            rec.etat = 'valide'
