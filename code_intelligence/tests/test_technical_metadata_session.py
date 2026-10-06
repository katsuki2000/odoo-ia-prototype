from unittest.mock import MagicMock

import pytest

from code_intelligence.graph import loader


@pytest.fixture
def connector_class(monkeypatch):
    connector = MagicMock()
    connector.username = "service_user"
    connector.authenticate.return_value = 4
    connector.search_read.return_value = [{"name": "account", "code": "fr_FR"}]
    connector_class = MagicMock(return_value=connector)
    monkeypatch.setattr("erp_data.odoo_connector.OdooConnector", connector_class)
    monkeypatch.setattr(loader, "read_runtime_translations", lambda *args: ([], {}))
    return connector_class


@pytest.mark.parametrize(
    "read",
    [
        lambda: loader._read_runtime_module_inventory(),
        lambda: loader._read_runtime_active_languages(),
        lambda: loader._read_runtime_translations(["fr_FR"], ["fr_FR"]),
        lambda: loader._discover_installed_core_modules(["account"]),
    ],
    ids=["inventory", "languages", "translations", "core_discovery"],
)
def test_instance_metadata_is_read_through_a_technical_connector(connector_class, read):
    read()

    connector_class.assert_called_once_with(technical=True)
    connector_class.return_value.authenticate.assert_called_once_with("service_user")
