import pytest

from evaluation import odoo_auth
from evaluation.preflight import BackendUnavailable


def _connector(calls, uid):
    class Connector:
        def __init__(self, db, password):
            self.db = db
            self.common = self
            calls.append(("connector", db, password))

        def authenticate(self, db, login, password, context):
            calls.append((db, login, password, context))
            return uid

    return Connector


def test_authentication_uses_the_explicit_benchmark_identity(monkeypatch):
    calls = []
    monkeypatch.setattr(odoo_auth, "OdooConnector", _connector(calls, 17))
    monkeypatch.setattr(odoo_auth.settings, "ODOO_DB", "odoo-test")
    assert odoo_auth.authenticate_odoo("analyst@example.test", "secret") == 17
    assert calls == [
        ("connector", "odoo-test", "secret"),
        ("odoo-test", "analyst@example.test", "secret", {}),
    ]


def test_a_refused_login_is_reported_as_a_backend_error(monkeypatch):
    monkeypatch.setattr(odoo_auth, "OdooConnector", _connector([], False))
    with pytest.raises(BackendUnavailable, match="analyst@example.test"):
        odoo_auth.authenticate_odoo("analyst@example.test", "wrong")
