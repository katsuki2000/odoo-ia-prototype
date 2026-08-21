"""
code_intelligence/tests/test_utils_p0.py

Unit tests for P0 Generalization utilities:
  - resolve_model_xmlref
  - discover_odoo_modules
  - compute_addons_hash
"""

import pytest
from pathlib import Path
from code_intelligence.utils import (
    resolve_model_xmlref,
    discover_odoo_modules,
    compute_addons_hash,
)


def test_resolve_model_xmlref():
    """Test resolution of various Odoo XML model references."""
    # Standard single model_ prefix
    assert resolve_model_xmlref("account.model_account_move") == "account.move"
    assert resolve_model_xmlref("model_account_move") == "account.move"

    # Multi-part compound model names
    assert resolve_model_xmlref("hr_expense.model_hr_expense_sheet") == "hr.expense.sheet"
    assert resolve_model_xmlref("model_hr_expense_sheet") == "hr.expense.sheet"

    # Custom module prefix
    assert resolve_model_xmlref("custom_credit_note_approval.model_account_move") == "account.move"

    # Already technical model names (no-op)
    assert resolve_model_xmlref("sale.order") == "sale.order"
    assert resolve_model_xmlref("account.move") == "account.move"
    assert resolve_model_xmlref("custom.purchase.request") == "custom.purchase.request"

    # Edge cases
    assert resolve_model_xmlref("") == ""
    assert resolve_model_xmlref(None) is None


def test_discover_odoo_modules(tmp_path):
    """Test auto-discovery of Odoo modules in an addons path."""
    addons = tmp_path / "addons"
    addons.mkdir()

    # Module 1
    (addons / "custom_sale").mkdir()
    (addons / "custom_sale" / "__manifest__.py").write_text("{'name': 'Custom Sale'}")

    # Module 2
    (addons / "custom_account").mkdir()
    (addons / "custom_account" / "__manifest__.py").write_text("{'name': 'Custom Account'}")

    # Non-module dir (no manifest)
    (addons / "random_folder").mkdir()

    # Discover all
    mods = discover_odoo_modules(addons)
    assert mods == ["custom_account", "custom_sale"]

    # Discover with prefix
    mods_prefix = discover_odoo_modules(addons, prefix="custom_sale")
    assert mods_prefix == ["custom_sale"]

    # Discover with exclude
    mods_exclude = discover_odoo_modules(addons, exclude={"custom_sale"})
    assert mods_exclude == ["custom_account"]


def test_compute_addons_hash(tmp_path):
    """Test hash computation for cache invalidation."""
    addons = tmp_path / "addons"
    addons.mkdir()
    mod = addons / "mod_a"
    mod.mkdir()
    (mod / "__manifest__.py").write_text("{'name': 'Mod A'}")
    (mod / "model.py").write_text("class MyModel: pass")

    h1 = compute_addons_hash(addons)
    assert len(h1) == 16

    # Modify file -> hash changes
    (mod / "model.py").write_text("class MyModel: x = 1")
    h2 = compute_addons_hash(addons)
    assert h1 != h2
