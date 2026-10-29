RENAMED_ROUTES = (('documentaire', 'documentation'), ('donnees_erp', 'system'))


def migrate(cr, version):
    for old, new in RENAMED_ROUTES:
        cr.execute(
            "UPDATE miro_ai_log SET metadata_text = replace(metadata_text, %s, %s) WHERE metadata_text LIKE %s",
            ('"%s"' % old, '"%s"' % new, '%"' + old + '"%'),
        )
