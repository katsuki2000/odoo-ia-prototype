"""
miro-rag/tests/test_odoo_connector.py

Integration and unit tests for the OdooConnector.
Validates authentication, read-only enforcement, and model whitelisting.
"""

import pytest
import os
from erp_data.odoo_connector import OdooConnector, OdooConnectorError
from erp_data._odoo_helpers import odoo_api_key_ctx


class _AccessDeniedModels:
    def __init__(self):
        self.calls = []

    def execute_kw(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        raise Exception("Access Denied")

@pytest.fixture(scope="module")
def odoo_connector():
    """Provides a configured OdooConnector instance."""
    url = os.getenv("ODOO_URL", "http://localhost:8069")
    db = os.getenv("ODOO_DB", "odoo-dev")
    password = os.getenv("ODOO_PASSWORD", "admin")
    return OdooConnector(url=url, db=db, password=password)

@pytest.fixture(scope="module")
def uid(odoo_connector):
    """Provides a valid uid for testing."""
    return odoo_connector.authenticate(odoo_connector.username)

@pytest.mark.integration
def test_authentication_success(odoo_connector):
    """Test successful authentication."""
    uid = odoo_connector.authenticate(odoo_connector.username)
    assert isinstance(uid, int)
    assert uid > 0

@pytest.mark.integration
def test_authentication_failure(odoo_connector):
    """Test failed authentication raises an error."""
    with pytest.raises(OdooConnectorError):
        # We need to temporarily change the connector password to simulate a bad login
        bad_connector = OdooConnector(
            url=odoo_connector.url, 
            db=odoo_connector.db, 
            password="wrong_password"
        )
        bad_connector.authenticate(bad_connector.username)


def test_username_comes_from_environment(monkeypatch):
    monkeypatch.setenv("ODOO_USERNAME", "service_user")

    connector = OdooConnector(url="http://odoo.invalid", db="test", password="secret")

    assert connector.username == "service_user"

def test_model_whitelist_enforcement(odoo_connector):
    """Verify that querying a non-whitelisted model raises an error."""
    with pytest.raises(OdooConnectorError) as exc_info:
        odoo_connector.search_read(1, "res.users", domain=[], fields=["name"])
    assert "not whitelisted" in str(exc_info.value)


@pytest.mark.parametrize(
    ("method", "args", "expected_message"),
    [
        ("search_read", (7, "res.partner", [], ["name"]), "Failed to read"),
        ("read_group", (7, "sale.order", [], ["amount_total:sum"], ["state"]), "Failed to aggregate"),
        ("fields_get", (7, "res.partner"), "Failed to fetch fields"),
    ],
)
def test_access_denied_with_api_key_never_retries_as_admin(method, args, expected_message):
    """An authorization failure must stay denied under the request identity."""
    connector = OdooConnector(url="http://odoo.invalid", db="test", password="admin-secret")
    denied_models = _AccessDeniedModels()
    connector.models = denied_models
    token = odoo_api_key_ctx.set("request-user-api-key")
    try:
        with pytest.raises(OdooConnectorError, match=expected_message):
            getattr(connector, method)(*args)
    finally:
        odoo_api_key_ctx.reset(token)

    assert len(denied_models.calls) == 1
    assert denied_models.calls[0][0][2] == "request-user-api-key"

def test_technical_connector_ignores_the_request_api_key():
    connector = OdooConnector(url="http://odoo.invalid", db="test", password="service-secret", technical=True)
    denied_models = _AccessDeniedModels()
    connector.models = denied_models
    token = odoo_api_key_ctx.set("request-user-api-key")
    try:
        with pytest.raises(OdooConnectorError):
            connector.search_read(2, "ir.module.module", [], ["name"])
    finally:
        odoo_api_key_ctx.reset(token)

    assert denied_models.calls[0][0][2] == "service-secret"


def test_default_connector_still_uses_the_request_api_key():
    connector = OdooConnector(url="http://odoo.invalid", db="test", password="service-secret")
    denied_models = _AccessDeniedModels()
    connector.models = denied_models
    token = odoo_api_key_ctx.set("request-user-api-key")
    try:
        with pytest.raises(OdooConnectorError):
            connector.search_read(2, "res.partner", [], ["name"])
    finally:
        odoo_api_key_ctx.reset(token)

    assert denied_models.calls[0][0][2] == "request-user-api-key"


class _RecordingModels:
    def __init__(self, result):
        self.calls = []
        self.result = result

    def execute_kw(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


def test_allowed_models_env_wildcard(monkeypatch):
    monkeypatch.setenv("ODOO_ALLOWED_MODELS", "*")
    connector = OdooConnector(url="http://odoo.invalid", db="test", password="secret")
    recorder = _RecordingModels([1, 2])
    connector.models = recorder
    token = odoo_api_key_ctx.set("k")
    try:
        assert connector.search(9, "hr.employee", domain=[], limit=2) == [1, 2]
    finally:
        odoo_api_key_ctx.reset(token)
    assert recorder.calls[0][0][3:6] == ("hr.employee", "search", [[]])


def test_search_read_count_name_search_dispatch(monkeypatch):
    connector = OdooConnector(url="http://odoo.invalid", db="test", password="secret")
    recorder = _RecordingModels([(10, "Acme")])
    connector.models = recorder
    token = odoo_api_key_ctx.set("k")
    try:
        assert connector.name_search(3, "res.partner", name="Ac", limit=5) == [(10, "Acme")]
        recorder.result = 4
        assert connector.search_count(3, "res.partner", [("is_company", "=", True)]) == 4
        recorder.result = [{"id": 10, "name": "Acme"}]
        assert connector.read(3, "res.partner", [10], fields=["name"]) == [
            {"id": 10, "name": "Acme"}
        ]
    finally:
        odoo_api_key_ctx.reset(token)


@pytest.mark.integration
@pytest.mark.parametrize("model", [
    "res.partner",
    "product.product",
    "sale.order",
    "account.move",
    "stock.quant",
    "project.task"
])
def test_whitelisted_models_search_read(odoo_connector, uid, model):
    """Confirm data retrieval works for each whitelisted model."""
    records = odoo_connector.search_read(
        uid=uid,
        model=model,
        domain=[],
        fields=["id"]
    )
    assert isinstance(records, list)

@pytest.mark.integration
def test_read_group_success(odoo_connector, uid):
    """Test aggregation query works for a whitelisted model."""
    results = odoo_connector.read_group(
        uid=uid,
        model="sale.order",
        domain=[],
        fields=["amount_total:sum"],
        groupby=["state"]
    )
    assert isinstance(results, list)
    if len(results) > 0:
        assert "state" in results[0]
        assert "amount_total" in results[0]

@pytest.mark.integration
def test_fields_get(odoo_connector, uid):
    """Test schema discovery."""
    fields = odoo_connector.fields_get(uid, "res.partner")
    assert isinstance(fields, dict)
    assert "name" in fields
    assert fields["name"]["type"] == "char"
