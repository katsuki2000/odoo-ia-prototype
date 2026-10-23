from odoo import models, fields, api
from odoo.exceptions import UserError


class CustomAssetLoan(models.Model):
    _name = 'custom.asset.loan'
    _description = "Mise a disposition de materiel"

    name = fields.Char()
    beneficiaire_id = fields.Many2one('res.users')
    materiel = fields.Char()
    date_debut = fields.Date()
    date_fin = fields.Date()
    demande_achat_liee_id = fields.Many2one('custom.purchase.request')
    etat = fields.Selection(
        [('brouillon', 'Brouillon'), ('en_cours', 'En cours'), ('restitue', 'Restitue')],
        default='brouillon'
    )

    def action_demarrer(self):
        for rec in self:
            # regle non documentee ailleurs : si le materiel (via la demande d'achat liee)
            # depasse 2000 euros, le beneficiaire doit etre different du demandeur d'origine
            if rec.demande_achat_liee_id and rec.demande_achat_liee_id.montant_estime > 2000:
                if rec.demande_achat_liee_id.demandeur_id == rec.beneficiaire_id:
                    raise UserError(
                        "Separation des roles requise : le beneficiaire d'un materiel de plus "
                        "de 2000 euros doit etre different du demandeur initial."
                    )
            rec.etat = 'en_cours'
