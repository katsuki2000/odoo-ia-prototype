"""
code_intelligence/tests/_corpus_paths.py

Shared corpus root paths for tests that read real Odoo modules from disk.

Re-exports the canonical corpus path constants from config.settings (single
source of truth for CORE_ADDONS_PATH/CUSTOM_ADDONS_PATH since contexte.txt
section 231), converted to Path objects for direct use by tests.

This module previously read its own env var (ODOO_CORE_ADDONS_PATH), which
contexte.txt section 244 confirmed is dead code -- never read by
config/settings.py -- so CORE_ADDONS_PATH silently resolved to None on any
machine that only sets the canonical CORE_ADDONS_PATH/CUSTOM_ADDONS_PATH in
.env, causing tests to skip gracefully but incorrectly (contexte.txt
section 260).

CUSTOM_ADDONS_PATH holds the project's own adversarial/custom modules
(committed in-repo under odoo_addons/, same on every machine).

CORE_ADDONS_PATH holds standard Odoo core modules (sale, account, ...),
which live in a real Odoo source checkout outside the repo. config.settings
always resolves it to a value (env override or portable sibling-directory
fallback), so tests must still guard with `.exists()` before use -- the
corpus itself may be genuinely absent on a given machine even though the
path is set.
"""

from pathlib import Path

from config.settings import CORE_ADDONS_PATH as _CORE_ADDONS_PATH_STR
from config.settings import CUSTOM_ADDONS_PATH as _CUSTOM_ADDONS_PATH_STR

CUSTOM_ADDONS_PATH = Path(_CUSTOM_ADDONS_PATH_STR)
CORE_ADDONS_PATH = Path(_CORE_ADDONS_PATH_STR)
