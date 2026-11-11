"""Offline unit tests for the schema discovery guard of the typed ORM tools."""

from unittest.mock import MagicMock

import pytest

from erp_data.connector.odoo_context import odoo_described_models_ctx, odoo_uid_ctx, request_identity
from erp_data.tools import langchain_tools, read_tools
from erp_data.runtime.errors import OrmRuntimeError, SchemaNotReadError
from erp_data.tools.read_tools import (
    orm_fields_get,
    orm_name_search,
    orm_read,
    orm_read_group,
    orm_search,
    orm_search_count,
    orm_search_read,
)

_FIELDS = {"move_type": {"type": "selection", "string": "Type", "selection": [["out_invoice", "Customer Invoice"]]}}


@pytest.fixture(autouse=True)
def _request_scope():
    connector = MagicMock()
    connector.fields_get.return_value = _FIELDS
    read_tools._connector = connector
    read_tools._field_cache.clear()
    with request_identity(7, "key"):
        yield connector
    read_tools._connector = None
    read_tools._field_cache.clear()


@pytest.mark.parametrize("query", [
    lambda: orm_search("account.move"),
    lambda: orm_search_read("account.move", fields=["name"]),
    lambda: orm_search_count("account.move"),
    lambda: orm_read_group("account.move", [], ["amount_total:sum"]),
])
def test_a_query_on_an_undescribed_model_is_refused_with_the_next_step(query, _request_scope):
    with pytest.raises(OrmRuntimeError, match="call fields_get on account.move without field_names"):
        query()
    _request_scope.search_count.assert_not_called()


def test_reading_the_fields_unlocks_the_model(_request_scope):
    orm_fields_get("account.move")
    _request_scope.search_count.return_value = 4
    assert orm_search_count("account.move").evidence[0].value == 4


def test_a_partial_fields_get_is_widened_and_describes_the_model(_request_scope):
    _request_scope.fields_get.return_value = {
        **_FIELDS,
        "state": {"type": "char", "string": "State"},
    }
    result = orm_fields_get("account.move", ["move_type"])
    _request_scope.fields_get.assert_called_once_with(7, "account.move", None)
    fields = result.evidence[0].value["fields"]
    assert set(fields) == {"move_type", "state"}
    assert fields["move_type"]["selection"] == [["out_invoice", "Customer Invoice"]]
    assert "note" in result.evidence[0].value
    _request_scope.search_count.return_value = 1
    orm_search_count("account.move")


def test_a_partial_fields_get_on_a_described_model_stays_partial(_request_scope):
    orm_fields_get("account.move")
    _request_scope.fields_get.reset_mock()
    orm_fields_get("account.move", ["move_type"])
    _request_scope.fields_get.assert_called_once_with(7, "account.move", ["move_type"])


def test_a_partial_fields_get_without_request_scope_stays_partial(_request_scope):
    token = odoo_described_models_ctx.set(None)
    try:
        orm_fields_get("account.move", ["move_type"])
    finally:
        odoo_described_models_ctx.reset(token)
    _request_scope.fields_get.assert_called_once_with(7, "account.move", ["move_type"])


def test_describing_one_model_does_not_unlock_another():
    orm_fields_get("account.move")
    with pytest.raises(OrmRuntimeError, match="fields of sale.order"):
        orm_search_count("sale.order")


def test_reads_by_id_and_name_resolution_need_no_description(_request_scope):
    _request_scope.read.return_value = [{"id": 1, "name": "A"}]
    _request_scope.name_search.return_value = [(1, "A")]
    assert orm_read("res.partner", ids=[1], fields=["name"]).observation.row_count == 1
    assert orm_name_search("res.partner", name="A").observation.row_count == 1


def test_each_request_starts_with_no_model_described():
    orm_fields_get("account.move")
    with request_identity(7, "key"):
        assert odoo_described_models_ctx.get() == set()
        with pytest.raises(OrmRuntimeError, match="not read yet"):
            orm_search_count("account.move")


def test_without_a_request_scope_the_guard_is_off(_request_scope):
    token = odoo_described_models_ctx.set(None)
    uid_token = odoo_uid_ctx.set(7)
    try:
        _request_scope.search_count.return_value = 1
        assert orm_search_count("account.move").evidence[0].value == 1
    finally:
        odoo_uid_ctx.reset(uid_token)
        odoo_described_models_ctx.reset(token)


def test_the_refusal_carries_the_model():
    with pytest.raises(SchemaNotReadError) as refused:
        orm_search_count("account.move")
    assert refused.value.model == "account.move"


@pytest.fixture
def _evidence(monkeypatch):
    monkeypatch.setattr(langchain_tools, "record_evidence", lambda evidence: None)


def test_a_query_automatically_reads_schema_then_retries(_request_scope, _evidence):
    _request_scope.search_count.return_value = 4
    observation = langchain_tools.search_count.invoke({"model": "account.move"})
    assert "account.move.search_count -> 4" in observation
    _request_scope.search_count.assert_called_once()


def test_unknown_field_names_come_with_the_advice_to_read_the_full_list(_evidence):
    observation = langchain_tools.fields_get.invoke({"model": "account.move", "field_names": ["payment_status"]})
    assert observation.endswith(langchain_tools.UNKNOWN_FIELDS_HINT)


def test_list_models_without_match_advises_the_english_term(_request_scope, _evidence):
    _request_scope.available_models.return_value = [{"model": "sale.order", "display_name": "Sales Order"}]
    observation = langchain_tools.list_models.invoke({"query": "commande"})
    assert observation.endswith(langchain_tools.NO_MODEL_HINT)


def test_list_models_with_a_match_gets_no_hint(_request_scope, _evidence):
    _request_scope.available_models.return_value = [{"model": "sale.order", "display_name": "Sales Order"}]
    observation = langchain_tools.list_models.invoke({"query": "sale"})
    assert langchain_tools.NO_MODEL_HINT not in observation


def test_a_detailed_fields_get_gets_no_hint(_evidence):
    observation = langchain_tools.fields_get.invoke({"model": "account.move", "field_names": ["move_type"]})
    assert langchain_tools.FULL_LIST_HINT not in observation
    assert langchain_tools.UNKNOWN_FIELDS_HINT not in observation


ASSET_LOAN = {"model": "custom.asset.loan", "display_name": "Mise a disposition de materiel"}
ACCENTED_LABEL = {"model": "hr.leave.type", "display_name": "Type de congé"}


@pytest.mark.parametrize("query", ["mise à disposition", "MATÉRIEL", "materiel", "mise a disposition"])
def test_list_models_ignores_accents_and_case_of_the_keyword(_request_scope, _evidence, query):
    _request_scope.available_models.return_value = [ASSET_LOAN, {"model": "sale.order", "display_name": "Sales Order"}]
    observation = langchain_tools.list_models.invoke({"query": query})
    assert "custom.asset.loan" in observation
    assert "sale.order" not in observation
    assert langchain_tools.NO_MODEL_HINT not in observation


@pytest.mark.parametrize("query", ["conge", "congé", "CONGÉ"])
def test_list_models_finds_an_accented_label_from_any_spelling(_request_scope, _evidence, query):
    _request_scope.available_models.return_value = [ACCENTED_LABEL]
    assert "hr.leave.type" in langchain_tools.list_models.invoke({"query": query})


def test_list_models_returns_the_label_as_odoo_writes_it(_request_scope, _evidence):
    _request_scope.available_models.return_value = [ACCENTED_LABEL]
    assert "Type de congé" in langchain_tools.list_models.invoke({"query": "conge"})


def test_list_models_folding_creates_no_false_match(_request_scope, _evidence):
    _request_scope.available_models.return_value = [ACCENTED_LABEL]
    observation = langchain_tools.list_models.invoke({"query": "matériel"})
    assert observation.endswith(langchain_tools.NO_MODEL_HINT)
