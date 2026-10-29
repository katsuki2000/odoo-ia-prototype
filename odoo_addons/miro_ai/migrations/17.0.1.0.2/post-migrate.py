def migrate(cr, version):
    cr.execute(
        """
        ALTER TABLE miro_ai_settings
        DROP COLUMN IF EXISTS activer_ventes,
        DROP COLUMN IF EXISTS activer_stocks,
        DROP COLUMN IF EXISTS activer_comptabilite,
        DROP COLUMN IF EXISTS activer_tickets
        """
    )
