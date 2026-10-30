"""Offline unit tests for P9 typed read-only ORM runtime tools."""

from unittest.mock import MagicMock

import pytest

from core.evidence.evidence import EvidenceSourceType
from erp_data.odoo_connector import OdooConnectorError
from erp_data.odoo_context import odoo_uid_ctx
from erp_data.runtime import read_tools
from erp_data.runtime.errors import OrmRuntimeError
from erp_data.runtime.read_tools import (
    READ_ONLY_ORM_TOOLS,
    orm_fields_get,
    orm_name_search,
    orm_read,
    orm_read_group,
    orm_search,
    orm_search_count,
    orm_search_read,
)
from erp_data.runtime.validation import (
    cap_name_search_limit,
    cap_row_limit,
    validate_domain,
    validate_field_list,
    validate_groupby,
    validate_model_name,
    validate_name_search_operator,
    validate_order,
    validate_record_ids,
)


@pytest.fixture(autouse=True)
def _reset_connector():
    read_tools._connector = read_tools._technical_connector = None
    yield
    read_tools._connector = read_tools._technical_connector = None


@pytest.fixture
def requester_uid():
    token = odoo_uid_ctx.set(7)
    yield 7
    odoo_uid_ctx.reset(token)


@pytest.fixture
def mock_connector():
    connector = MagicMock()
    read_tools._connector = connector
    return connector


def test_read_only_tool_registry_covers_first_lot():
    assert set(READ_ONLY_ORM_TOOLS) == {
        "fields_get",
        "search",
        "read",
        "search_read",
        "search_count",
        "read_group",
        "name_search",
    }


def test_validate_model_name_rejects_invalid():
    with pytest.raises(OrmRuntimeError):
        validate_model_name("Res.Partner")
    with pytest.raises(OrmRuntimeError):
        validate_model_name("sale.order;drop")
    assert validate_model_name("sale.order") == "sale.order"
    assert validate_model_name("x_custom.record") == "x_custom.record"
    with pytest.raises(OrmRuntimeError):
        validate_model_name("x_custom.record\n")


def test_validate_domain_accepts_leaves_and_operators():
    assert validate_domain([("state", "=", "sale"), "|", ("id", ">", 0)]) == [
        ("state", "=", "sale"),
        "|",
        ("id", ">", 0),
    ]
    with pytest.raises(OrmRuntimeError):
        validate_domain("bad")
    with pytest.raises(OrmRuntimeError):
        validate_domain([("a", "=")])
    with pytest.raises(OrmRuntimeError, match="invalid domain leaf operator"):
        validate_domain([("name", "execute", "x")])
    with pytest.raises(OrmRuntimeError, match="invalid domain field"):
        validate_domain([("name);write", "=", "x")])
    assert validate_order("write_date desc, id asc") == "write_date desc, id asc"
    with pytest.raises(OrmRuntimeError):
        validate_order("name desc; unlink")
    assert validate_name_search_operator("ilike") == "ilike"
    with pytest.raises(OrmRuntimeError):
        validate_name_search_operator("execute")


def test_validate_field_list_blocks_aggregates_unless_allowed():
    assert validate_field_list(["name", "partner_id"]) == ["name", "partner_id"]
    with pytest.raises(OrmRuntimeError):
        validate_field_list(["amount_total:sum"])
    assert validate_field_list(["amount_total:sum"], allow_aggregate=True) == [
        "amount_total:sum"
    ]


def test_cap_limits_from_settings(monkeypatch):
    monkeypatch.setattr("config.settings.ORM_RUNTIME_MAX_ROWS", 50)
    monkeypatch.setattr("config.settings.ORM_NAME_SEARCH_LIMIT", 10)
    assert cap_row_limit(None) == 50
    assert cap_row_limit(200) == 50
    assert cap_row_limit(20) == 20
    assert cap_name_search_limit(100) == 10


def test_identity_refuses_without_uid(mock_connector):
    with pytest.raises(OrmRuntimeError, match="no requester uid"):
        orm_search_count("res.partner")


def test_orm_search_count_builds_observation_and_evidence(
    requester_uid, mock_connector
):
    mock_connector.search_count.return_value = 3
    result = orm_search_count("res.partner", domain=[("is_company", "=", True)])

    mock_connector.search_count.assert_called_once_with(
        uid=7, model="res.partner", domain=[("is_company", "=", True)]
    )
    assert result.observation.tool == "search_count"
    assert result.observation.execution_identity == 7
    assert result.observation.row_count == 1
    assert result.evidence[0].source_type == EvidenceSourceType.ORM
    assert result.evidence[0].value == 3
    assert result.evidence[0].scope["execution_identity"] == 7
    assert "search_count -> 3" in result.text


def test_orm_search_applies_row_cap_and_truncation_flag(
    requester_uid, mock_connector, monkeypatch
):
    monkeypatch.setattr("config.settings.ORM_RUNTIME_MAX_ROWS", 5)
    mock_connector.search.return_value = [1, 2, 3, 4, 5]
    result = orm_search("sale.order", domain=[], limit=999)

    mock_connector.search.assert_called_once_with(
        7, "sale.order", domain=[], limit=5, order=None, offset=0
    )
    assert result.observation.truncated is True
    assert "[truncated]" in result.text


def test_orm_read_requires_explicit_fields(requester_uid, mock_connector):
    with pytest.raises(OrmRuntimeError, match="explicit non-empty list"):
        orm_read("res.partner", ids=[1], fields=None)
    mock_connector.read.return_value = [{"id": 1, "name": "Acme"}]
    result = orm_read("res.partner", ids=[1], fields=["name"])
    assert result.observation.method == "read"
    assert result.evidence[0].value == [{"id": 1, "name": "Acme"}]


def test_orm_search_read_requires_fields_and_caps(
    requester_uid, mock_connector, monkeypatch
):
    monkeypatch.setattr("config.settings.ORM_RUNTIME_MAX_ROWS", 2)
    mock_connector.search_read.return_value = [{"id": 1}, {"id": 2}]
    result = orm_search_read(
        "product.product",
        domain=[("active", "=", True)],
        fields=["name"],
        limit=50,
    )
    mock_connector.search_read.assert_called_once_with(
        uid=7,
        model="product.product",
        domain=[("active", "=", True)],
        fields=["name"],
        limit=2,
        order=None,
    )
    assert result.observation.truncated is True


def test_orm_name_search_uses_separate_ceiling(
    requester_uid, mock_connector, monkeypatch
):
    monkeypatch.setattr("config.settings.ORM_NAME_SEARCH_LIMIT", 3)
    mock_connector.name_search.return_value = [(1, "A"), (2, "B"), (3, "C")]
    result = orm_name_search("res.partner", name="Ac", limit=100)
    mock_connector.name_search.assert_called_once_with(
        7,
        "res.partner",
        name="Ac",
        domain=[],
        operator="ilike",
        limit=3,
    )
    assert result.observation.truncated is True
    assert result.evidence[0].value == [(1, "A"), (2, "B"), (3, "C")]


def test_orm_fields_get_and_read_group(requester_uid, mock_connector):
    mock_connector.fields_get.return_value = {
        "name": {"type": "char", "string": "Name"},
        "email": {"type": "char", "string": "Email"},
    }
    fg = orm_fields_get("res.partner")
    assert fg.observation.row_count == 2
    assert fg.evidence[0].value["field_count"] == 2

    mock_connector.read_group.return_value = [{"state": "sale", "amount_total": 10.0}]
    rg = orm_read_group(
        "sale.order",
        domain=[],
        fields=["amount_total:sum"],
        groupby=["state"],
        lazy=False,
    )
    mock_connector.read_group.assert_called_once_with(
        uid=7,
        model="sale.order",
        domain=[],
        fields=["amount_total:sum"],
        groupby=["state"],
        lazy=False,
    )
    assert rg.observation.method == "read_group"


def test_orm_fields_get_treats_an_empty_name_list_as_the_index(requester_uid, mock_connector):
    mock_connector.fields_get.return_value = {"state": {"type": "selection", "string": "Status"}}
    result = read_tools.orm_fields_get("sale.order", [])
    mock_connector.fields_get.assert_called_once_with(7, "sale.order", [])
    assert result.evidence[0].value["fields"] == {"state": "selection: Status"}


def test_orm_read_group_without_groupby_returns_one_total(requester_uid, mock_connector):
    mock_connector.read_group.return_value = [{"__count": 4, "amount_total": 143175.0}]
    orm_read_group("account.move", domain=[], fields=["amount_total:sum"], groupby=[])
    orm_read_group("account.move", domain=[], fields=["amount_total:sum"])
    assert [call.kwargs["groupby"] for call in mock_connector.read_group.call_args_list] == [[], []]


def test_validate_groupby_still_rejects_bad_names():
    assert validate_groupby(None) == []
    with pytest.raises(OrmRuntimeError):
        validate_groupby("state")
    with pytest.raises(OrmRuntimeError):
        validate_groupby(["state; drop"])


def test_orm_read_rejects_too_many_ids(requester_uid, monkeypatch):
    monkeypatch.setattr("config.settings.ORM_RUNTIME_MAX_ROWS", 2)
    with pytest.raises(OrmRuntimeError, match="too many record ids"):
        validate_record_ids([1, 2, 3], max_rows=2)


def test_connector_error_becomes_orm_runtime_error(requester_uid, mock_connector):

    mock_connector.search_count.side_effect = OdooConnectorError(
        "Failed to count res.partner: Access Denied"
    )
    with pytest.raises(OrmRuntimeError, match="Access Denied"):
        orm_search_count("res.partner")


def test_orm_fields_get_without_names_returns_a_compact_index(requester_uid, mock_connector):
    mock_connector.fields_get.return_value = {
        "state": {"type": "selection", "string": "Status", "selection": [["draft", "Quotation"]]},
        "partner_id": {"type": "many2one", "string": "Customer", "relation": "res.partner"},
    }
    result = orm_fields_get("sale.order")
    mock_connector.fields_get.assert_called_once_with(7, "sale.order", [])
    assert result.evidence[0].value["fields"] == {
        "partner_id": "many2one(res.partner): Customer",
        "state": "selection: Status",
    }


def test_orm_fields_get_with_names_returns_details_and_reports_unknown_fields(requester_uid, mock_connector):
    mock_connector.fields_get.return_value = {
        "state": {"type": "selection", "string": "Status", "selection": [["sale", "Sales Order"]], "extra": 1},
    }
    result = orm_fields_get("sale.order", ["state", "missing_field"])
    mock_connector.fields_get.assert_called_once_with(7, "sale.order", ["state", "missing_field"])
    value = result.evidence[0].value
    assert value["fields"] == {"state": {"type": "selection", "string": "Status", "selection": [["sale", "Sales Order"]]}}
    assert value["unknown_fields"] == ["missing_field"]
