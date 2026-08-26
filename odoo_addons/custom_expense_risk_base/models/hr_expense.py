from odoo import models, fields


class HrExpense(models.Model):
    _inherit = 'hr.expense'

    # Champs bruts (non calculés) portant l'information de risque de base.
    # Volontairement stockés ici et nulle part ailleurs : le module
    # custom_expense_risk_score (dependance en aval) les consomme dans
    # un champ calcule cross-module -- c'est le cas adversarial vise
    # (Bloc 9 : "champs calcules cross-module").
    justificatif_manquant = fields.Boolean(
        string="Justificatif manquant",
        help="Coche manuellement par le comptable si la piece jointe (facture/ticket) est absente ou illisible.",
    )
    nombre_relances = fields.Integer(
        string="Nombre de relances",
        help="Nombre de fois ou l'employe a ete relance pour fournir un justificatif.",
    )
