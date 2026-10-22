# the test parser scans every comment in the file and
# mistakes a prose explanation for a real annotation.

from odoo import models
from odoo.tools.sql import create_unique_index, create_index, index_exists


class AccountMoveLikeUnique(models.Model):
    _inherit = 'account.move'

    # Unique index created by raw execute(), never visible via _sql_constraints
    # nor @api.constrains.
    def _auto_init(self):
        super()._auto_init()
        # ruleid: odoo-raw-sql-unique-index
        if not index_exists(self.env.cr, 'account_move_unique_name'):
            self.env.cr.execute("""
                CREATE UNIQUE INDEX account_move_unique_name
                                 ON account_move(name, journal_id)
                              WHERE (state = 'posted' AND name != '/')
            """)


class NonUniqueIndexModel(models.Model):
    _inherit = 'stock.move'

    def _auto_init(self):
        super()._auto_init()
        # ok: odoo-raw-sql-unique-index
        # CREATE INDEX simple (pas UNIQUE) -- ne doit PAS matcher.
        self.env.cr.execute("""
            CREATE INDEX stock_move_state_idx ON stock_move(state)
        """)


class UnrelatedExecuteCall(models.Model):
    _inherit = 'sale.order'

    def action_confirm_custom(self):
        # ok: odoo-raw-sql-unique-index
        # .execute() unrelated to SQL -- the argument is not a
        # string containing "CREATE UNIQUE INDEX", must NOT match.
        wizard = self.env['some.wizard'].create({})
        return wizard.execute(self)


class HelperUniqueIndex(models.Model):
    _inherit = 'purchase.order'

    def init(self):
        super().init()
        # ruleid: odoo-create-unique-index-helper
        create_unique_index(
            self.env.cr,
            indexname='purchase_order_custom_uniq',
            tablename='purchase_order',
            expressions=['partner_id', 'origin'],
        )


class HelperNonUniqueIndex(models.Model):
    _inherit = 'purchase.order.line'

    def init(self):
        super().init()
        # ok: odoo-create-unique-index-helper
        # create_index (non-unique) -- nom de fonction different, ne doit
        # PAS matcher la regle unique.
        create_index(
            self.env.cr,
            indexname='purchase_order_line_custom_idx',
            tablename='purchase_order_line',
            expressions=['product_id'],
        )
