# the test parser scans every comment in the file and
# mistakes a prose explanation for a real annotation.

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
        # Read (attribute access), not a declaration -- must NOT
        # match.
        # ok: odoo-sql-constraints-declaration
        existing = self._sql_constraints
        return existing


class ConstraintBackupMixin(models.AbstractModel):
    _name = 'constraint.backup.mixin'

    # Different name (_backup suffix) -- must NOT match: the exact
    # `_sql_constraints` token is required.
    # ok: odoo-sql-constraints-declaration
    _sql_constraints_backup = [
        ('old_uniq', 'unique(old_field)', 'Ancien message.'),
    ]


class InvoiceOverride(models.Model):
    _inherit = 'account.move'

    # Dynamic override through comprehension + concatenation -- OUT OF SCOPE
    # (gap documented in sql_constraints.yaml), so it must
    # NOT match for now.
    # ok: odoo-sql-constraints-declaration
    _sql_constraints = [
        c for c in models.Model._sql_constraints if c[0] != 'name_uniq'
    ] + [
        ('new_name_uniq', 'unique(name, company_id)',
         'Doit être unique par société.'),
    ]
