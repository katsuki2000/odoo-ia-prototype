import importlib.util
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[2] / "odoo_addons/miro_ai/migrations/17.0.1.0.3/pre-migration.py"


class _Cursor:
    def __init__(self, has_column):
        self.has_column = has_column
        self.statements = []
        self.rowcount = 4

    def execute(self, statement):
        self.statements.append(" ".join(statement.split()))

    def fetchone(self):
        return (1,) if self.has_column else None


def _migrate(cursor):
    spec = importlib.util.spec_from_file_location("miro_ai_pre_migration_1_0_3", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.migrate(cursor, "17.0.1.0.2")


def test_archived_turns_are_erased_before_the_column_is_dropped():
    cursor = _Cursor(has_column=True)

    _migrate(cursor)

    assert cursor.statements[1:] == [
        "DELETE FROM miro_ai_log WHERE active IS NOT TRUE",
        "ALTER TABLE miro_ai_log DROP COLUMN active",
    ]


def test_migration_does_nothing_when_the_column_is_already_gone():
    cursor = _Cursor(has_column=False)

    _migrate(cursor)

    assert len(cursor.statements) == 1
