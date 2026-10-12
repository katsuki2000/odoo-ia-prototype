from pathlib import Path

import pytest

ADDONS_DIR = Path(__file__).resolve().parents[1] / "odoo_addons"
ADDON_SOURCES = sorted(path for path in ADDONS_DIR.rglob("*.py") if "__pycache__" not in path.parts)


@pytest.mark.parametrize("source", ADDON_SOURCES, ids=lambda path: str(path.relative_to(ADDONS_DIR)))
def test_addon_source_compiles_on_the_running_interpreter(source):
    compile(source.read_text(encoding="utf-8"), str(source), "exec")
