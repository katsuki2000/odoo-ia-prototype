"""
erp_data/tests/test_get_order_count.py

get_order_count_raw() answers "combien de commandes" via typed
orm_search_count (P9). Pure unit tests -- connector.search_count is mocked.
"""

import pytest
from unittest.mock import patch

from erp_data.tools.sales import (
    get_order_count_raw,
    get_order_count,
    get_total_sales_raw,
)
from erp_data.odoo_context import odoo_uid_ctx
from core.evidence.evidence import Evidence, EvidenceSourceType


def _domain(mock_call):
    kwargs = mock_call.call_args.kwargs
    if "domain" in kwargs:
        return kwargs["domain"]
    return mock_call.call_args.args[2]


def test_get_order_count_raw_returns_text_and_evidence():
    with patch("erp_data._odoo_helpers.connector.search_count") as mock_search_count:
        mock_search_count.return_value = 12
        token = odoo_uid_ctx.set(7)
        try:
            text, evidence = get_order_count_raw(
                client="", periode="le mois dernier", statut="toutes"
            )
        finally:
            odoo_uid_ctx.reset(token)

    assert isinstance(text, str)
    assert "12" in text
    assert isinstance(evidence, Evidence)
    assert evidence.source_type == EvidenceSourceType.ORM
    assert evidence.value == 12
    assert evidence.source == "sale.order:search_count"


def test_get_order_count_raw_empty_result_returns_zero_not_none():
    with patch("erp_data._odoo_helpers.connector.search_count") as mock_search_count:
        mock_search_count.return_value = 0
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence = get_order_count_raw(client="Personne")
        finally:
            odoo_uid_ctx.reset(token)

    assert "0" in text
    assert evidence.value == 0
    assert evidence.source_type == EvidenceSourceType.ORM


def test_get_order_count_raw_no_confidence_set():
    with patch("erp_data._odoo_helpers.connector.search_count") as mock_search_count:
        mock_search_count.return_value = 5
        token = odoo_uid_ctx.set(1)
        try:
            _text, evidence = get_order_count_raw()
        finally:
            odoo_uid_ctx.reset(token)

    assert evidence.confidence is None


def test_get_order_count_raw_evidence_scope_carries_execution_identity():
    with patch("erp_data._odoo_helpers.connector.search_count") as mock_search_count:
        mock_search_count.return_value = 5
        token = odoo_uid_ctx.set(42)
        try:
            _text, evidence = get_order_count_raw()
        finally:
            odoo_uid_ctx.reset(token)

    assert evidence.scope["execution_identity"] == 42
    assert "read_at" in evidence.scope
    assert "company_id" not in evidence.scope


def test_get_order_count_tool_wrapper_returns_plain_string():
    with patch("erp_data._odoo_helpers.connector.search_count") as mock_search_count:
        mock_search_count.return_value = 4
        token = odoo_uid_ctx.set(1)
        try:
            result = get_order_count.invoke(
                {"client": "", "periode": "", "statut": "toutes"}
            )
        finally:
            odoo_uid_ctx.reset(token)

    assert isinstance(result, str)
    assert "4" in result


def test_get_order_count_tool_wrapper_catches_connector_exceptions():
    with patch("erp_data._odoo_helpers.connector.search_count") as mock_search_count:
        mock_search_count.side_effect = RuntimeError("boom")
        token = odoo_uid_ctx.set(1)
        try:
            result = get_order_count.invoke(
                {"client": "", "periode": "", "statut": "toutes"}
            )
        finally:
            odoo_uid_ctx.reset(token)

    assert "Erreur lors du comptage des commandes" in result


def test_get_order_count_raw_propagates_exceptions_without_fabricating_evidence():
    with patch("erp_data._odoo_helpers.connector.search_count") as mock_search_count:
        mock_search_count.side_effect = RuntimeError("boom")
        token = odoo_uid_ctx.set(1)
        try:
            raised = False
            try:
                get_order_count_raw()
            except RuntimeError:
                raised = True
        finally:
            odoo_uid_ctx.reset(token)

    assert raised


@pytest.mark.parametrize(
    "statut,expected_states",
    [
        ("toutes", ["draft", "sent", "sale", "done"]),
        ("confirmees", ["sale", "done"]),
        ("brouillon", ["draft", "sent"]),
        ("annulees", ["cancel"]),
    ],
)
def test_get_order_count_raw_domain_matches_statut_contract(statut, expected_states):
    with patch("erp_data._odoo_helpers.connector.search_count") as mock_search_count:
        mock_search_count.return_value = 1
        token = odoo_uid_ctx.set(1)
        try:
            get_order_count_raw(client="", periode="", statut=statut)
        finally:
            odoo_uid_ctx.reset(token)

    assert _domain(mock_search_count) == [("state", "in", expected_states)]


def test_get_order_count_raw_unknown_statut_falls_back_to_toutes_domain():
    with patch("erp_data._odoo_helpers.connector.search_count") as mock_search_count:
        mock_search_count.return_value = 1
        token = odoo_uid_ctx.set(1)
        try:
            get_order_count_raw(client="", periode="", statut="n'importe quoi")
        finally:
            odoo_uid_ctx.reset(token)

    assert _domain(mock_search_count) == [
        ("state", "in", ["draft", "sent", "sale", "done"])
    ]


@pytest.mark.parametrize("statut", ["toutes", "confirmees", "brouillon", "annulees"])
def test_get_order_count_and_get_total_sales_share_identical_domain_per_statut(statut):
    with patch("erp_data._odoo_helpers.connector.search_count") as mock_sc_count:
        mock_sc_count.return_value = 1
        token = odoo_uid_ctx.set(1)
        try:
            get_order_count_raw(client="", periode="", statut=statut)
        finally:
            odoo_uid_ctx.reset(token)
        count_domain = _domain(mock_sc_count)

    with patch("erp_data._odoo_helpers.connector.read_group") as mock_rg_total:
        mock_rg_total.return_value = [{"amount_total": 100.0}]
        token = odoo_uid_ctx.set(1)
        try:
            get_total_sales_raw(client="", periode="", statut=statut)
        finally:
            odoo_uid_ctx.reset(token)
        total_domain = mock_rg_total.call_args.kwargs["domain"]

    assert count_domain == total_domain


def test_get_order_count_raw_period_filter_applies_date_range():
    with patch("erp_data._odoo_helpers.connector.search_count") as mock_search_count, patch(
        "erp_data._odoo_helpers.parse_period"
    ) as mock_parse_period:
        mock_parse_period.return_value = ("2026-08-01", "2026-08-31")
        mock_search_count.return_value = 7
        token = odoo_uid_ctx.set(1)
        try:
            get_order_count_raw(client="", periode="le mois dernier", statut="toutes")
        finally:
            odoo_uid_ctx.reset(token)

    called_domain = _domain(mock_search_count)
    assert ("date_order", ">=", "2026-08-01") in called_domain
    assert ("date_order", "<=", "2026-08-31 23:59:59") in called_domain
