"""
code_intelligence/tests/_corpus_paths.py

Shared corpus root paths for tests that read real Odoo modules from disk.

CUSTOM_ADDONS_PATH holds the project's own adversarial/custom modules
(committed in-repo under odoo_addons/, same on every machine).

CORE_ADDONS_PATH holds standard Odoo core modules (sale, account, ...),
which live in a real Odoo source checkout outside the repo and whose
location differs per workstation -- set via the ODOO_CORE_ADDONS_PATH
env var in .env. It is None when unset, so tests relying on it must
skip gracefully (pytest.skip) rather than assert a hard failure.
"""

import os
from pathlib import Path

CUSTOM_ADDONS_PATH = Path(__file__).resolve().parents[2] / "odoo_addons"

_core_env = os.getenv("ODOO_CORE_ADDONS_PATH")
CORE_ADDONS_PATH = Path(_core_env) if _core_env else None
