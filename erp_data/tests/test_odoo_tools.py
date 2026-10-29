"""Security guarantees of the Odoo connector: read-only surface and optional model allowlist."""

import pytest

from config import settings
from erp_data.odoo_connector import OdooConnector, OdooConnectorError


def test_read_only_enforcement():
    connector = OdooConnector(url="http://odoo.invalid", db="test", password="unused")
    assert not hasattr(connector, "write")
    assert not hasattr(connector, "create")
    assert not hasattr(connector, "unlink")


def test_optional_model_allowlist_enforcement(monkeypatch):
    monkeypatch.setattr(settings, "ODOO_ALLOWED_MODELS", frozenset({"res.partner"}))
    restricted = OdooConnector(url="http://odoo.invalid", db="test", password="unused")
    with pytest.raises(OdooConnectorError, match="ODOO_ALLOWED_MODELS"):
        restricted.search_read(1, "x_custom.record", [], [])
