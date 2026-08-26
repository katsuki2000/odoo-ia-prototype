from odoo import models, fields, api


class HrExpense(models.Model):
    _inherit = 'hr.expense'

    # CROSS-MODULE, 2 hops : risk_score n'est pas declare ici -- il vient
    # de custom_expense_risk_score, qui lui-meme depend de champs de
    # custom_expense_risk_base (voir ce module). Chaine complete :
    #   custom_expense_risk_base (justificatif_manquant, nombre_relances)
    #     -> custom_expense_risk_score (risk_score)
    #       -> custom_expense_risk_alert (alerte_conformite, ce fichier)
    #
    # CHEMIN POINTE : 'employee_id.department_id' est un @api.depends sur
    # un sous-champ d'un modele relie (hr.employee), pas un champ direct
    # de hr.expense -- teste la resolution partielle des dependances
    # relationnelles (python_extractor/graph_builder ne retiennent que le
    # premier segment 'employee_id' comme noeud DEPENDS_ON, le chemin
    # complet etant conserve en attribut d'arete 'trigger_path').
    alerte_conformite = fields.Boolean(
        string="Alerte conformite",
        compute='_compute_alerte_conformite',
        store=True,
        help="Alerte si le score de risque est eleve ou si le departement de "
             "l'employe est soumis a un controle renforce.",
    )

    @api.depends('risk_score', 'employee_id.department_id')
    def _compute_alerte_conformite(self):
        for rec in self:
            departement = rec.employee_id.department_id.name or ''
            controle_renforce = 'Direction' in departement or 'Finance' in departement
            rec.alerte_conformite = rec.risk_score >= 50 or controle_renforce
