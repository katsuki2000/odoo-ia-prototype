"""
code_intelligence/tests/test_bloc_n1_core_module_discovery.py

Coverage for CORE_MODULE_CANDIDATES / _discover_installed_core_modules()
(code_intelligence/graph/loader.py) -- previously untested (todo/contexte.txt
section 753). Locks two things:

1. CORE_MODULE_CANDIDATES covers the full Bloc N1 perimeter (5 modules:
   account, sale, stock, purchase, maintenance) -- 'maintenance' was added
   in this section specifically to close the gap flagged in section 752
   (it was not preloaded into the production graph unless it happened to
   be a direct dependency of an already-loaded custom/OCA module).
2. _discover_installed_core_modules() itself: filters candidates down to
   what ir.module.module (state=installed) reports on the live instance,
   and falls back to the full candidate list (unfiltered) whenever that
   query cannot be trusted -- connector raises, or returns no matches at
   all (todo/rules.md: machine-dependent values need an explicit fallback,
   never a silent hard assumption).

OdooConnector is imported inside the function body (deferred import
pattern, code_intelligence/agent/tools convention) specifically so it can
be intercepted here via monkeypatch.setattr on erp_data.odoo_connector.
"""

from unittest.mock import MagicMock

from code_intelligence.graph.loader import (
    CORE_MODULE_CANDIDATES,
    _discover_installed_core_modules,
    _discover_installed_source_modules,
    _read_runtime_active_languages,
    _read_runtime_module_inventory,
)


def test_core_module_candidates_covers_bloc_n1_perimeter():
    """The 5 Bloc N1 modules (sections 747-748) must all be candidates."""
    assert set(CORE_MODULE_CANDIDATES) == {
        "account", "sale", "stock", "purchase", "maintenance",
    }


def test_discover_filters_to_actually_installed_modules(monkeypatch):
    """Only candidates reported installed by ir.module.module are kept."""
    mock_connector = MagicMock()
    mock_connector.authenticate.return_value = 1
    mock_connector.search_read.return_value = [
        {"name": "account"}, {"name": "sale"}, {"name": "maintenance"},
    ]
    mock_connector_cls = MagicMock(return_value=mock_connector)
    monkeypatch.setattr(
        "erp_data.odoo_connector.OdooConnector", mock_connector_cls
    )

    result = _discover_installed_core_modules(CORE_MODULE_CANDIDATES)

    assert result == ["account", "sale", "maintenance"]
    mock_connector.search_read.assert_called_once()
    call_kwargs = mock_connector.search_read.call_args.kwargs
    assert call_kwargs["model"] == "ir.module.module"
    assert call_kwargs["domain"] == [
        ("state", "=", "installed"),
        ("name", "in", CORE_MODULE_CANDIDATES),
    ]


def test_discover_falls_back_to_full_list_on_connector_error(monkeypatch):
    """Instance unreachable (offline build, no live Odoo) -> full candidate
    list unfiltered, never a silent empty preload."""
    mock_connector_cls = MagicMock(side_effect=ConnectionError("unreachable"))
    monkeypatch.setattr(
        "erp_data.odoo_connector.OdooConnector", mock_connector_cls
    )

    result = _discover_installed_core_modules(CORE_MODULE_CANDIDATES)

    assert result == CORE_MODULE_CANDIDATES


def test_discover_falls_back_to_full_list_when_query_returns_nothing(monkeypatch):
    """A query that succeeds but reports zero installed candidates is
    treated the same as an unreachable instance -- safer than silently
    loading no core modules at all."""
    mock_connector = MagicMock()
    mock_connector.authenticate.return_value = 1
    mock_connector.search_read.return_value = []
    mock_connector_cls = MagicMock(return_value=mock_connector)
    monkeypatch.setattr(
        "erp_data.odoo_connector.OdooConnector", mock_connector_cls
    )

    result = _discover_installed_core_modules(CORE_MODULE_CANDIDATES)

    assert result == CORE_MODULE_CANDIDATES


def test_discover_excludes_maintenance_when_not_installed(monkeypatch):
    """Regression pin for the exact gap flagged in section 752/753:
    'maintenance' must be excluded when the live instance reports it as
    not installed, not silently kept."""
    mock_connector = MagicMock()
    mock_connector.authenticate.return_value = 1
    mock_connector.search_read.return_value = [
        {"name": "account"}, {"name": "sale"},
        {"name": "stock"}, {"name": "purchase"},
    ]
    mock_connector_cls = MagicMock(return_value=mock_connector)
    monkeypatch.setattr(
        "erp_data.odoo_connector.OdooConnector", mock_connector_cls
    )

    result = _discover_installed_core_modules(CORE_MODULE_CANDIDATES)

    assert "maintenance" not in result
    assert result == ["account", "sale", "stock", "purchase"]


def test_runtime_inventory_reads_all_installed_modules(monkeypatch):
    mock_connector = MagicMock()
    mock_connector.authenticate.return_value = 1
    mock_connector.search_read.return_value = [{
        "name": "custom_sales",
        "installed_version": "17.0.1.0",
        "latest_version": "17.0.1.0",
        "state": "installed",
    }]
    monkeypatch.setattr(
        "erp_data.odoo_connector.OdooConnector", MagicMock(return_value=mock_connector),
    )

    inventory = _read_runtime_module_inventory()

    assert inventory == mock_connector.search_read.return_value
    assert mock_connector.search_read.call_args.kwargs == {
        "uid": 1,
        "model": "ir.module.module",
        "domain": [("state", "=", "installed")],
        "fields": ["name", "installed_version", "latest_version", "state"],
    }


def test_discover_uses_provided_inventory_without_new_connector_call():
    result = _discover_installed_core_modules(
        CORE_MODULE_CANDIDATES,
        [{"name": "account"}, {"name": "maintenance"}],
    )

    assert result == ["account", "maintenance"]


def test_runtime_active_languages_reads_only_language_codes(monkeypatch):
    mock_connector = MagicMock()
    mock_connector.username = "service_user"
    mock_connector.authenticate.return_value = 3
    mock_connector.search_read.return_value = [
        {"code": "fr_FR"}, {"code": "en_US"}, {"code": "fr_FR"},
    ]
    monkeypatch.setattr(
        "erp_data.odoo_connector.OdooConnector", MagicMock(return_value=mock_connector),
    )

    languages = _read_runtime_active_languages()

    assert languages == ["en_US", "fr_FR"]
    assert mock_connector.search_read.call_args.kwargs == {
        "uid": 3,
        "model": "res.lang",
        "domain": [("active", "=", True)],
        "fields": ["code"],
    }


def test_discover_installed_source_modules_uses_path_priority(tmp_path):
    framework = tmp_path / "framework"
    core = tmp_path / "core"
    custom = tmp_path / "custom"
    for root, module_name in (
        (framework, "base"),
        (core, "sale"),
        (core, "duplicate"),
        (custom, "duplicate"),
    ):
        module_dir = root / module_name
        module_dir.mkdir(parents=True)
        (module_dir / "__manifest__.py").write_text("{}", encoding="utf-8")

    modules = _discover_installed_source_modules(
        [framework, core, custom],
        [{"name": "base"}, {"name": "sale"}, {"name": "duplicate"}, {"name": "missing"}],
    )

    assert modules == {
        "base": framework / "base",
        "sale": core / "sale",
        "duplicate": custom / "duplicate",
    }
