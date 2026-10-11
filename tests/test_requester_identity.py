import pytest

from erp_data import _odoo_helpers
from erp_data.odoo_connector import OdooConnectorError
from erp_data.odoo_context import odoo_uid_ctx
from erp_data.runtime.errors import OrmRuntimeError
from erp_data.runtime.identity import require_execution_uid


@pytest.fixture
def no_odoo(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("no call to Odoo is allowed while resolving the requester")

    monkeypatch.setattr(_odoo_helpers.connector, "authenticate", forbidden)
    monkeypatch.setattr(_odoo_helpers.connector, "common", None)


def test_get_current_uid_refuses_without_a_requester(no_odoo):
    with pytest.raises(OdooConnectorError, match="No requester uid"):
        _odoo_helpers.get_current_uid()


def test_get_current_uid_returns_the_requester_uid_without_calling_odoo(no_odoo):
    token = odoo_uid_ctx.set(42)
    try:
        assert _odoo_helpers.get_current_uid() == 42
    finally:
        odoo_uid_ctx.reset(token)


def test_get_current_uid_keeps_no_cache_between_requests(no_odoo):
    token = odoo_uid_ctx.set(7)
    odoo_uid_ctx.reset(token)
    with pytest.raises(OdooConnectorError):
        _odoo_helpers.get_current_uid()


def test_require_execution_uid_is_always_strict(no_odoo):
    with pytest.raises(OrmRuntimeError, match="no requester uid"):
        require_execution_uid()
    token = odoo_uid_ctx.set("9")
    try:
        assert require_execution_uid() == 9
    finally:
        odoo_uid_ctx.reset(token)
