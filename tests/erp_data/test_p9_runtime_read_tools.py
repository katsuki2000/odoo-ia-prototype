"""Offline unit tests for P9 typed read-only ORM runtime tools."""

from unittest.mock import MagicMock

import pytest

from core.evidence import EvidenceSourceType
from erp_data.connector.odoo_connector import OdooConnectorError
from erp_data.connector.odoo_context import odoo_uid_ctx
from erp_data.tools import read_tools
from erp_data.runtime.errors import OrmRuntimeError
from erp_data.tools.read_tools import (
    READ_ONLY_ORM_TOOLS,
    orm_fields_get,
    orm_list_models,
    orm_name_search,
    orm_read,
    orm_read_group,
    orm_search,
    orm_search_count,
    orm_search_read,
)
from erp_data.runtime.validation import (
    assert_selection_values,
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
        "list_models",
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
    with pytest.raises(OrmRuntimeError, match="flat list"):
        validate_domain([("stage_id", "not in", [[6]])])
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
    mock_connector.search.return_value = [1, 2, 3, 4, 5, 6]
    result = orm_search("sale.order", domain=[], limit=999)

    mock_connector.search.assert_called_once_with(
        7, "sale.order", domain=[], limit=6, order=None, offset=0
    )
    assert result.evidence[0].value == [1, 2, 3, 4, 5]
    assert result.observation.truncated is True
    assert "[truncated]" in result.text


def test_a_result_exactly_at_the_limit_is_not_truncated(
    requester_uid, mock_connector, monkeypatch
):
    monkeypatch.setattr("config.settings.ORM_RUNTIME_MAX_ROWS", 5)
    mock_connector.search.return_value = [1, 2, 3, 4, 5]
    result = orm_search("sale.order", domain=[], limit=5)

    assert result.observation.truncated is False
    assert "[truncated]" not in result.text


def test_orm_read_group_cuts_to_the_ceiling_and_flags_the_rest(
    requester_uid, mock_connector, monkeypatch
):
    monkeypatch.setattr("config.settings.ORM_RUNTIME_MAX_ROWS", 2)
    mock_connector.read_group.return_value = [{"id": 1}, {"id": 2}, {"id": 3}]
    result = orm_read_group("sale.order", domain=[], fields=["amount_total:sum"], groupby=["partner_id"])

    assert result.evidence[0].value == [{"id": 1}, {"id": 2}]
    assert result.observation.truncated is True


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
    mock_connector.search_read.return_value = [{"id": 1}, {"id": 2}, {"id": 3}]
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
        limit=3,
        order=None,
    )
    assert result.evidence[0].value == [{"id": 1}, {"id": 2}]
    assert result.observation.truncated is True


def test_list_models_keeps_models_matching_every_keyword_in_name_or_label(requester_uid, mock_connector):
    mock_connector.available_models.return_value = [
        {"model": "estate.property", "display_name": "Estate Property"},
        {"model": "product.template", "display_name": "Product"},
        {"model": "product.product", "display_name": "Product Variant"},
    ]
    result = orm_list_models("Product variant")
    assert result.evidence[0].value == [("product.product", "Product Variant")]
    assert result.observation.truncated is False
    mock_connector.available_models.assert_called_once_with(7)


def test_list_models_includes_sibling_models_from_the_matching_namespace(requester_uid, mock_connector):
    mock_connector.available_models.return_value = [
        {"model": "account.invoice.report", "display_name": "Invoices Statistics"},
        {"model": "account.move", "display_name": "Journal Entry"},
        {"model": "sale.order", "display_name": "Sales Order"},
    ]
    result = orm_list_models("invoice")
    assert result.evidence[0].value == [
        ("account.invoice.report", "Invoices Statistics"),
        ("account.move", "Journal Entry"),
    ]


def test_list_models_marks_a_truncated_list_only_when_more_models_exist(requester_uid, mock_connector, monkeypatch):
    monkeypatch.setattr("config.settings.ORM_RUNTIME_MAX_ROWS", 2)
    mock_connector.available_models.return_value = [
        {"model": f"x.model{index}", "display_name": f"Model {index}"} for index in range(3)
    ]
    assert orm_list_models("model").observation.truncated is True
    assert orm_list_models("model 0").observation.truncated is False


def test_a_missing_model_error_points_to_list_models(requester_uid, mock_connector):
    mock_connector.name_search.side_effect = OdooConnectorError("Object real.estate.property doesn't exist")
    with pytest.raises(OrmRuntimeError, match="list_models"):
        orm_name_search("real.estate.property", name="a")


def test_list_models_requires_a_keyword(requester_uid, mock_connector):
    with pytest.raises(OrmRuntimeError):
        orm_list_models("  ")


def test_orm_name_search_uses_separate_ceiling(
    requester_uid, mock_connector, monkeypatch
):
    monkeypatch.setattr("config.settings.ORM_NAME_SEARCH_LIMIT", 3)
    mock_connector.name_search.return_value = [(1, "A"), (2, "B"), (3, "C"), (4, "D")]
    result = orm_name_search("res.partner", name="Ac", limit=100)
    mock_connector.name_search.assert_called_once_with(
        7,
        "res.partner",
        name="Ac",
        domain=[],
        operator="ilike",
        limit=4,
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


_SALE_STATES = [["draft", "Quotation"], ["sent", "Quotation Sent"], ["sale", "Sales Order"], ["cancel", "Cancelled"]]


def test_assert_selection_values_lists_the_valid_values():
    choices = {"state": _SALE_STATES}.get
    assert_selection_values([("state", "in", ["sale", "draft"]), ("amount", ">", 1)], choices)
    assert_selection_values([("state", "=", False), ("name", "=", "S0001")], choices)
    with pytest.raises(OrmRuntimeError, match=r"'confirmed'.*sale \(Sales Order\)"):
        assert_selection_values([("state", "=", "confirmed")], choices)
    with pytest.raises(OrmRuntimeError, match="'done'"):
        assert_selection_values([("state", "not in", ["sale", "done"])], choices)


def test_read_group_refuses_an_unknown_selection_value_before_calling_odoo(requester_uid, mock_connector):
    mock_connector.fields_get.return_value = {"state": {"type": "selection", "selection": _SALE_STATES}}
    with pytest.raises(OrmRuntimeError, match="valid values: draft"):
        orm_read_group("sale.order", [("state", "=", "confirmed")], ["amount_total:sum"])
    mock_connector.read_group.assert_not_called()


def test_selection_metadata_is_fetched_once_per_model_and_field(requester_uid, mock_connector):
    mock_connector.fields_get.return_value = {"state": {"type": "selection", "selection": _SALE_STATES}}
    mock_connector.search_count.return_value = 3
    orm_search_count("sale.order", [("state", "=", "sale")])
    orm_search_count("sale.order", [("state", "in", ["sale", "sent"])])
    mock_connector.fields_get.assert_called_once_with(7, "sale.order", ["state"])


def test_selection_check_follows_relations_and_skips_other_leaves(requester_uid, mock_connector):
    mock_connector.fields_get.side_effect = lambda uid, model, names: {
        ("sale.order.line", "order_id"): {"order_id": {"type": "many2one", "relation": "sale.order"}},
        ("sale.order", "state"): {"state": {"type": "selection", "selection": _SALE_STATES}},
        ("sale.order.line", "active"): {"active": {"type": "boolean"}},
        ("sale.order.line", "qty"): {"qty": {"type": "float"}},
    }.get((model, names[0]), {})
    with pytest.raises(OrmRuntimeError, match="'confirmed'"):
        orm_search_count("sale.order.line", [("order_id.state", "=", "confirmed")])
    mock_connector.search_count.return_value = 1
    orm_search_count("sale.order.line", [("active", "=", True), ("qty", ">", 2)])
    assert mock_connector.fields_get.call_count == 4


def test_selection_check_is_skipped_when_the_field_is_not_a_selection(requester_uid, mock_connector):
    mock_connector.fields_get.return_value = {"name": {"type": "char"}}
    mock_connector.search_count.return_value = 5
    assert orm_search_count("res.partner", [("name", "=", "Acme")]).observation.row_count == 1


def test_domain_on_unknown_field_is_refused_with_close_names(requester_uid, mock_connector):
    def fields_get(uid, model, names):
        if names:
            return {n: {"type": "char"} for n in names if n in {"probability", "stage_id", "active"}}
        return {"probability": {}, "stage_id": {}, "active": {}, "state_id": {}}

    mock_connector.fields_get.side_effect = fields_get
    with pytest.raises(OrmRuntimeError, match=r"unknown field 'state'.*crm\.lead.*fields_get") as exc:
        orm_search_count("crm.lead", domain=[("state", "!=", "won")])
    assert "state_id" in str(exc.value)
    mock_connector.search_count.assert_not_called()


def test_domain_on_unknown_related_field_is_refused_before_xmlrpc(requester_uid, mock_connector):
    def fields_get(uid, model, names):
        if model == "crm.lead" and names == ["stage_id"]:
            return {"stage_id": {"type": "many2one", "relation": "crm.stage"}}
        if model == "crm.stage" and names == ["closed"]:
            return {}
        if model == "crm.stage" and not names:
            return {"name": {}, "is_won": {}}
        return {}

    mock_connector.fields_get.side_effect = fields_get
    with pytest.raises(OrmRuntimeError, match=r"unknown field 'stage_id.closed'.*crm\.stage"):
        orm_search_count("crm.lead", domain=[("stage_id.closed", "=", False)])
    mock_connector.search_count.assert_not_called()


def test_domain_on_known_or_undetermined_field_reaches_the_orm(requester_uid, mock_connector):
    mock_connector.fields_get.side_effect = lambda uid, model, names: {
        n: {"type": "boolean"} for n in names if n == "active"
    }
    mock_connector.search_count.return_value = 2
    assert orm_search_count("crm.lead", domain=[("active", "=", True)]).observation.row_count == 1

    read_tools._field_cache.clear()
    mock_connector.fields_get.side_effect = OdooConnectorError("down")
    mock_connector.search_count.return_value = 2
    orm_search_count("crm.lead", domain=[("anything", "=", 1)])
    mock_connector.search_count.assert_called()


def test_odoo_traceback_is_reduced_to_its_last_line(requester_uid, mock_connector):
    fault = (
        "Failed to count crm.lead: <Fault 1: 'Traceback (most recent call last):\\n"
        "  File \"x.py\", line 1, in f\\n    boom()\\n"
        "ValueError: Invalid field crm.lead.foo in leaf (\\'foo\\', \\'=\\', 1)\\n'>"
    )
    mock_connector.fields_get.side_effect = lambda uid, model, names: {n: {"type": "char"} for n in names}
    mock_connector.search_count.side_effect = OdooConnectorError(fault)
    with pytest.raises(OrmRuntimeError) as exc:
        orm_search_count("crm.lead", domain=[("foo", "=", 1)])
    message = str(exc.value)
    assert "Traceback" not in message and "File" not in message
    assert "ValueError: Invalid field crm.lead.foo in leaf ('foo', '=', 1)" in message


@pytest.mark.parametrize(
    "metadata, groupby, expected_groupby, expected_lazy",
    [
        ({"amount_total": {"type": "monetary", "currency_field": "currency_id"}, "currency_id": {"store": True}}, [], ["currency_id"], False),
        ({"amount_total": {"type": "monetary", "currency_field": "currency_id"}, "currency_id": {"store": True}}, ["partner_id"], ["partner_id", "currency_id"], False),
        ({"amount_total": {"type": "monetary", "currency_field": "currency_id"}, "currency_id": {"store": True}}, ["currency_id"], ["currency_id"], True),
        ({"amount_total": {"type": "monetary", "currency_field": "company_currency"}, "company_currency": {"store": False}}, [], [], True),
        ({"amount_total": {"type": "float"}}, [], [], True),
    ],
)
def test_orm_read_group_never_sums_amounts_of_different_currencies(
    requester_uid, mock_connector, metadata, groupby, expected_groupby, expected_lazy
):
    mock_connector.fields_get.side_effect = lambda uid, model, names: {names[0]: metadata[names[0]]}
    mock_connector.read_group.return_value = []
    orm_read_group("sale.order", domain=[], fields=["amount_total:sum"], groupby=groupby)

    call = mock_connector.read_group.call_args.kwargs
    assert call["groupby"] == expected_groupby
    assert call["lazy"] is expected_lazy


def _to_many_connector(mock_connector, name_rows):
    mock_connector.fields_get.side_effect = lambda uid, model, names: {
        "user_ids": {"type": "many2many", "relation": "res.users"},
        "name": {"type": "char"},
    }
    mock_connector.search_read.return_value = [
        {"id": 1, "name": "A", "user_ids": [6, 2]},
        {"id": 2, "name": "B", "user_ids": []},
        {"id": 3, "name": "C", "user_ids": [2]},
    ]
    mock_connector.read.side_effect = name_rows


def test_search_read_names_the_ids_of_a_to_many_field(requester_uid, mock_connector):
    _to_many_connector(mock_connector, lambda uid, model, ids, fields: [
        {"id": 2, "display_name": "Marc Demo"}, {"id": 6, "display_name": "Mitchell Admin"},
    ])
    result = orm_search_read("project.task", fields=["name", "user_ids"])
    rows = result.evidence[0].value
    assert rows[0]["user_ids"] == [[6, "Mitchell Admin"], [2, "Marc Demo"]]
    assert rows[1]["user_ids"] == [] and rows[2]["user_ids"] == [[2, "Marc Demo"]]
    assert rows[0]["name"] == "A"
    mock_connector.read.assert_called_once_with(7, "res.users", [2, 6], fields=["display_name"])


def test_to_many_ids_are_kept_when_their_names_cannot_be_read(requester_uid, mock_connector):
    def refused(uid, model, ids, fields):
        raise OdooConnectorError("access denied")

    _to_many_connector(mock_connector, refused)
    rows = orm_search_read("project.task", fields=["name", "user_ids"]).evidence[0].value
    assert rows[0]["user_ids"] == [6, 2]
