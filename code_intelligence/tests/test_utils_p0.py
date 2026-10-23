"""
code_intelligence/tests/test_utils_p0.py

Unit tests for P0 Generalization utilities:
  - resolve_model_xmlref
  - discover_odoo_modules
  - compute_addons_hash
"""

from code_intelligence.utils import (
    resolve_model_xmlref,
    discover_odoo_modules,
    compute_addons_hash,
    format_xml_id_citation,
    format_xml_id_citations,
)


def test_format_xml_id_citation_valid_identifier():
    """Bug 1 (todo/contexte.txt section 490, option A): a real
    module-qualified xml_id gets the exact 'xml_id: ' prefix
    sourcing_guard._XML_ID_PATTERN looks for as ground truth."""
    assert format_xml_id_citation("account.group_account_manager") == (
        "xml_id: account.group_account_manager"
    )


def test_format_xml_id_citation_rejects_unqualified_identifier():
    """No dot -- not a real xml_id, never emitted as a citation token
    (would never match sourcing_guard's own pattern anyway)."""
    assert format_xml_id_citation("group_account_manager") == ""
    assert format_xml_id_citation("") == ""
    assert format_xml_id_citation(None) == ""


def test_format_xml_id_citations_joins_with_spaces_not_commas():
    """Each token space-joined, never comma-joined -- sourcing_guard's
    _XML_ID_PATTERN stops at the first non-identifier character, so a
    comma-joined list would only ever yield the first id as ground truth."""
    result = format_xml_id_citations(
        ["account.group_account_manager", "sales_team.group_sale_manager", "bare_name"]
    )
    assert result == "xml_id: account.group_account_manager xml_id: sales_team.group_sale_manager"


def test_resolve_model_xmlref():
    """Test resolution of various Odoo XML model references."""
    # Standard single model_ prefix
    assert resolve_model_xmlref("account.model_account_move") == "account.move"
    assert resolve_model_xmlref("model_account_move") == "account.move"

    # Multi-part compound model names
    assert resolve_model_xmlref("hr_expense.model_hr_expense_sheet") == "hr.expense.sheet"
    assert resolve_model_xmlref("model_hr_expense_sheet") == "hr.expense.sheet"

    # Custom module prefix
    assert resolve_model_xmlref("miro_credit_note_approval.model_account_move") == "account.move"

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
