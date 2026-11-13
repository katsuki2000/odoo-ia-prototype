"""Conversations archived before deletion became permanent are erased, then the unused `active` column is dropped.

Runs before the models are loaded. Without it, removing the field would make the old archived
conversations reappear in the users' history.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name = 'miro_ai_log' AND column_name = 'active'"
    )
    if not cr.fetchone():
        return
    cr.execute("DELETE FROM miro_ai_log WHERE active IS NOT TRUE")
    _logger.info("miro_ai: %s archived conversation turns erased", cr.rowcount)
    cr.execute("ALTER TABLE miro_ai_log DROP COLUMN active")
