# Fixtures TDD (semgrep --test) pour la règle
# odoo-sql-constraints-declaration (Bloc 3 / J11).
#
# Attention : ne pas décrire ici en toutes lettres le nom des deux
# annotations attendues par semgrep --test (positive / negative) —
# le parseur de tests scanne tous les commentaires du fichier et
# confond une explication en prose avec une vraie annotation.

from odoo import models, fields


class SaleOrderCustom(models.Model):
    _inherit = 'sale.order'

    reference_code = fields.Char()

    # Cas standard : liste d'un seul tuple de contrainte.
    # ruleid: odoo-sql-constraints-declaration
    _sql_constraints = [
        ('reference_code_uniq', 'unique(reference_code)',
         'Le code de référence doit être unique !'),
    ]


class AssetLoan(models.Model):
    _name = 'asset.loan'
    _description = 'Asset Loan'

    asset_id = fields.Many2one('asset.asset')
    borrower_id = fields.Many2one('res.partner')

    # Cas standard : liste de plusieurs tuples (unique + check SQL).
    # ruleid: odoo-sql-constraints-declaration
    _sql_constraints = [
        ('asset_borrower_uniq', 'unique(asset_id, borrower_id)',
         'Cet actif est déjà prêté à ce partenaire !'),
        ('check_dates',
         'CHECK(date_return IS NULL OR date_return > date_start)',
         'La date de retour doit être postérieure à la date de début !'),
    ]


class PartnerHelper(models.Model):
    _inherit = 'res.partner'

    def _get_existing_constraints(self):
        # Lecture (attribute access), pas une déclaration — ne doit PAS
        # matcher.
        # ok: odoo-sql-constraints-declaration
        existing = self._sql_constraints
        return existing


class ConstraintBackupMixin(models.AbstractModel):
    _name = 'constraint.backup.mixin'

    # Nom différent (suffixe _backup) — ne doit PAS matcher : le token
    # exact `_sql_constraints` est requis.
    # ok: odoo-sql-constraints-declaration
    _sql_constraints_backup = [
        ('old_uniq', 'unique(old_field)', 'Ancien message.'),
    ]


class InvoiceOverride(models.Model):
    _inherit = 'account.move'

    # Surcharge dynamique par compréhension + concaténation — HORS
    # PÉRIMÈTRE J11 (gap documenté dans sql_constraints.yaml), ne doit
    # donc PAS matcher pour l'instant.
    # ok: odoo-sql-constraints-declaration
    _sql_constraints = [
        c for c in models.Model._sql_constraints if c[0] != 'name_uniq'
    ] + [
        ('new_name_uniq', 'unique(name, company_id)',
         'Doit être unique par société.'),
    ]
