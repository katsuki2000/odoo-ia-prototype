"""P9: session company scope on typed ORM reads."""

from unittest.mock import MagicMock

import pytest

from erp_data.odoo_context import (
    odoo_company_id_ctx,
    odoo_company_ids_ctx,
    odoo_uid_ctx,
)
from erp_data.odoo_connector import OdooConnector
from erp_data.runtime.errors import OrmRuntimeError
from erp_data.runtime.identity import resolve_company_scope
from erp_data.runtime.read_tools import orm_search_count, set_connector_for_tests
from erp_data.runtime.validation import assert_domain_within_companies


@pytest.fixture(autouse=True)
def _reset_connector():
    set_connector_for_tests(None)
    yield
    set_connector_for_tests(None)


def test_resolve_company_scope_defaults_ids_to_active():
    t1 = odoo_company_id_ctx.set(2)
    t2 = odoo_company_ids_ctx.set(None)
    try:
        assert resolve_company_scope() == (2, [2])
    finally:
        odoo_company_id_ctx.reset(t1)
        odoo_company_ids_ctx.reset(t2)


def test_assert_domain_rejects_foreign_company():
    with pytest.raises(OrmRuntimeError, match="outside allowed"):
        assert_domain_within_companies(
            [("company_id", "=", 9)],
            allowed_company_ids=[2],
        )
    with pytest.raises(OrmRuntimeError, match="outside allowed"):
        assert_domain_within_companies(
            [("company_id", "in", [2, 9])],
            allowed_company_ids=[2],
        )
    assert_domain_within_companies(
        [("company_id", "in", [2])],
        allowed_company_ids=[2],
    )


def test_search_count_scope_and_connector_context():
    connector = MagicMock()
    connector.search_count.return_value = 1
    set_connector_for_tests(connector)
    # Use real connector path for context injection separately
    uid_t = odoo_uid_ctx.set(7)
    cid_t = odoo_company_id_ctx.set(2)
    cids_t = odoo_company_ids_ctx.set([2])
    try:
        result = orm_search_count("res.partner", domain=[("is_company", "=", True)])
    finally:
        odoo_uid_ctx.reset(uid_t)
        odoo_company_id_ctx.reset(cid_t)
        odoo_company_ids_ctx.reset(cids_t)

    assert result.observation.company_id == 2
    assert result.observation.company_ids == [2]
    assert result.evidence[0].scope["company_id"] == 2
    assert result.evidence[0].scope["company_ids"] == [2]


def test_search_count_refuses_domain_outside_scope():
    set_connector_for_tests(MagicMock())
    uid_t = odoo_uid_ctx.set(7)
    cid_t = odoo_company_id_ctx.set(2)
    cids_t = odoo_company_ids_ctx.set([2])
    try:
        with pytest.raises(OrmRuntimeError, match="outside allowed"):
            orm_search_count("sale.order", domain=[("company_id", "=", 1)])
    finally:
        odoo_uid_ctx.reset(uid_t)
        odoo_company_id_ctx.reset(cid_t)
        odoo_company_ids_ctx.reset(cids_t)


def test_connector_injects_allowed_company_ids():
    connector = OdooConnector(url="http://odoo.invalid", db="test", password="secret")
    recorder = MagicMock()
    recorder.execute_kw.return_value = 0
    connector.models = recorder
    cid_t = odoo_company_id_ctx.set(5)
    cids_t = odoo_company_ids_ctx.set([5])
    try:
        connector.search_count(3, "res.partner", [])
    finally:
        odoo_company_id_ctx.reset(cid_t)
        odoo_company_ids_ctx.reset(cids_t)

    kwargs = recorder.execute_kw.call_args[0][6]
    assert kwargs["context"]["force_company"] == 5
    assert kwargs["context"]["allowed_company_ids"] == [5]
