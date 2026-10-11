from types import SimpleNamespace

import pytest

from code_intelligence.agent.rpc_client import OdooRpcClient
from config import settings
from config.odoo_credentials import MissingServiceCredentialError, service_login, service_password
from core.evaluation import instance_runtime as ir
from erp_data.odoo_connector import OdooConnector
from tests.eval_instance_helpers import make_env, make_spec

VARIABLES = ("ODOO_ADMIN_PASSWORD", "ODOO_PASSWORD", "ODOO_ADMIN_LOGIN", "ODOO_USERNAME")


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for variable in VARIABLES:
        monkeypatch.delenv(variable, raising=False)


def test_no_password_is_configured_means_an_explicit_error():
    with pytest.raises(MissingServiceCredentialError, match="ODOO_ADMIN_PASSWORD"):
        service_password()


def test_password_priority_and_fallback_variable(monkeypatch):
    monkeypatch.setenv("ODOO_PASSWORD", "from-password")
    assert service_password() == "from-password"
    monkeypatch.setenv("ODOO_ADMIN_PASSWORD", "from-admin")
    assert service_password() == "from-admin"


def test_login_priority_and_default(monkeypatch):
    assert service_login() == "admin"
    monkeypatch.setenv("ODOO_USERNAME", "svc")
    assert service_login() == "svc"
    monkeypatch.setenv("ODOO_ADMIN_LOGIN", "robot")
    assert service_login() == "robot"


def test_connector_is_built_without_a_secret_and_refuses_when_one_is_needed():
    connector = OdooConnector(url="http://odoo.invalid", db="test", technical=True)
    with pytest.raises(MissingServiceCredentialError):
        connector.password
    with pytest.raises(MissingServiceCredentialError):
        connector._resolve_password()


def test_connector_reads_the_environment_when_used_and_explicit_password_wins(monkeypatch):
    monkeypatch.setenv("ODOO_ADMIN_PASSWORD", "from-env")
    technical = OdooConnector(url="http://odoo.invalid", db="test", technical=True)
    assert technical._resolve_password() == "from-env"
    explicit = OdooConnector(url="http://odoo.invalid", db="test", password="explicit")
    assert explicit.password == "explicit"
    explicit.password = "changed"
    assert explicit.password == "changed"


def test_connector_username_follows_the_configuration(monkeypatch):
    monkeypatch.setenv("ODOO_ADMIN_LOGIN", "robot")
    assert OdooConnector(url="http://odoo.invalid", db="test").username == "robot"


def rpc_client(calls):
    client = OdooRpcClient(url="http://odoo.invalid", db="test")
    client.common = SimpleNamespace(authenticate=lambda db, login, password, context: calls.append((login, password)) or 7)
    return client


def test_rpc_client_refuses_to_authenticate_without_a_configured_password():
    calls = []
    with pytest.raises(MissingServiceCredentialError):
        rpc_client(calls).authenticate_admin()
    assert calls == []


def test_rpc_client_authenticates_with_the_configured_service_account(monkeypatch):
    monkeypatch.setenv("ODOO_ADMIN_PASSWORD", "from-env")
    monkeypatch.setenv("ODOO_ADMIN_LOGIN", "robot")
    calls = []
    assert rpc_client(calls).authenticate_admin() == 7
    assert calls == [("robot", "from-env")]


def test_worker_environment_gives_instances_their_own_service_password(tmp_path):
    values = ir.worker_environment(
        make_spec(), make_env(tmp_path), "http://127.0.0.1:1", {"ODOO_ADMIN_PASSWORD": "operator-secret"},
    )
    assert values["ODOO_ADMIN_PASSWORD"] == settings.EVAL_INSTANCE_ADMIN_PASSWORD
    assert "operator-secret" not in values.values()
