from odoo import models, fields, api


class HrExpense(models.Model):
    _inherit = 'hr.expense'

    # CROSS-MODULE : justificatif_manquant et nombre_relances ne sont PAS
    # declares dans ce module (ni dans ce fichier) -- ils viennent de
    # acme_expense_risk_base, un module de DEPENDANCE, pas de ce
    # module-ci. total_amount vient du coeur hr_expense et est lui-meme
    # un champ calcule (_compute_total_amount).
    risk_score = fields.Integer(
        string="Score de risque",
        compute='_compute_risk_score',
        store=True,
        help="Score de risque de la note de frais, combinant justificatif manquant, "
             "relances et montant total.",
    )

    @api.depends('justificatif_manquant', 'nombre_relances', 'total_amount')
    def _compute_risk_score(self):
        for rec in self:
            score = 0
            if rec.justificatif_manquant:
                score += 50
            score += min(rec.nombre_relances, 5) * 10
            if rec.total_amount > 1000:
                score += 20
            rec.risk_score = score
