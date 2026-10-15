# le parseur de tests scanne tous les commentaires du fichier et
# confond une explication en prose avec une vraie annotation.

from odoo import models
from odoo.tools.sql import create_unique_index, create_index, index_exists


class AccountMoveLikeUnique(models.Model):
    _inherit = 'account.move'

    # Cas reel qui a motive la regle (account.move : todo/contexte.txt
    # section 811/812) -- index unique cree par execute() brut, jamais
    # visible via _sql_constraints ni @api.constrains.
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
        # .execute() sans rapport avec du SQL -- l'argument n'est pas une
        # chaine contenant "CREATE UNIQUE INDEX", ne doit PAS matcher.
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
