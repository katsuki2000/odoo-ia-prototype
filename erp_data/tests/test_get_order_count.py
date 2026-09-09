"""
erp_data/tests/test_get_order_count.py

New ORM tool (todo/contexte.txt section 522): get_order_count_raw()/
get_order_count(). Answers "combien de commandes" questions with a single
read_group(fields=[]) count, rejected as an extension of get_sale_details
because that tool's per-order sale.order.line lookup is an N+1-query
design built for itemized detail, not a global count -- see the
comparative analysis in the same journal section. Mirrors the coverage
pattern already established for get_total_sales_raw
(test_bloc_b0_evidence_orm_pilot.py) and get_average_sales_raw
(test_bloc_b1_evidence_get_average_sales.py). Pure unit tests --
connector.read_group is mocked so these never touch a live Odoo instance.
"""

import pytest
from unittest.mock import patch

from erp_data.tools.sales import (
    get_order_count_raw,
    get_order_count,
    get_total_sales_raw,
)
from erp_data.odoo_context import odoo_uid_ctx
from core.evidence import Evidence, EvidenceSourceType


def test_get_order_count_raw_returns_text_and_evidence():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [{"__count": 12}]
        token = odoo_uid_ctx.set(7)
        try:
            text, evidence = get_order_count_raw(client="", periode="le mois dernier", statut="toutes")
        finally:
            odoo_uid_ctx.reset(token)

    assert isinstance(text, str)
    assert "12" in text
    assert isinstance(evidence, Evidence)
    assert evidence.source_type == EvidenceSourceType.ORM
    assert evidence.value == 12
    assert evidence.source == "sale.order:read_group(__count)"


def test_get_order_count_raw_only_requests_count_no_sum_or_avg_field():
    """The whole point of this tool over get_sale_details is a single
    aggregation query with no per-record payload -- fields must stay
    empty so Odoo returns __count alone."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [{"__count": 3}]
        token = odoo_uid_ctx.set(1)
        try:
            get_order_count_raw()
        finally:
            odoo_uid_ctx.reset(token)

    assert mock_read_group.call_args.kwargs["fields"] == []
    assert mock_read_group.call_args.kwargs["groupby"] == []


def test_get_order_count_raw_empty_result_returns_zero_not_none():
    """Unlike get_total_sales_raw (amount unknown -> None), an empty
    read_group result for a count is a real, positive fact: zero orders
    matched, not an absence of data -- same discipline as
    list_out_of_stock_products_raw's zero-rupture case."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = []
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence = get_order_count_raw(client="Personne")
        finally:
            odoo_uid_ctx.reset(token)

    assert "0" in text
    assert evidence.value == 0
    assert evidence.source_type == EvidenceSourceType.ORM


def test_get_order_count_raw_no_confidence_set():
    """B0 decision (todo/contexte.txt section 426): a deterministic ORM
    read never carries a confidence score."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [{"__count": 5}]
        token = odoo_uid_ctx.set(1)
        try:
            _text, evidence = get_order_count_raw()
        finally:
            odoo_uid_ctx.reset(token)

    assert evidence.confidence is None


def test_get_order_count_raw_evidence_scope_carries_execution_identity():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [{"__count": 5}]
        token = odoo_uid_ctx.set(42)
        try:
            _text, evidence = get_order_count_raw()
        finally:
            odoo_uid_ctx.reset(token)

    assert evidence.scope["execution_identity"] == 42
    assert "read_at" in evidence.scope
    assert "company_id" not in evidence.scope  # not fabricated, see _orm_evidence_scope


def test_get_order_count_tool_wrapper_returns_plain_string():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [{"__count": 4}]
        token = odoo_uid_ctx.set(1)
        try:
            result = get_order_count.invoke({"client": "", "periode": "", "statut": "toutes"})
        finally:
            odoo_uid_ctx.reset(token)

    assert isinstance(result, str)
    assert "4" in result


def test_get_order_count_tool_wrapper_catches_connector_exceptions():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.side_effect = RuntimeError("boom")
        token = odoo_uid_ctx.set(1)
        try:
            result = get_order_count.invoke({"client": "", "periode": "", "statut": "toutes"})
        finally:
            odoo_uid_ctx.reset(token)

    assert "Erreur lors du comptage des commandes" in result


def test_get_order_count_raw_propagates_exceptions_without_fabricating_evidence():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.side_effect = RuntimeError("boom")
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


# -----------------------------------------------------------------------------
# _resolve_statut() domain contract (same mandate as todo/contexte.txt
# section 516's coverage for get_total_sales_raw/get_average_sales_raw)
# -----------------------------------------------------------------------------

@pytest.mark.parametrize("statut,expected_states", [
    ("toutes", ["draft", "sent", "sale", "done"]),
    ("confirmees", ["sale", "done"]),
    ("brouillon", ["draft", "sent"]),
    ("annulees", ["cancel"]),
])
def test_get_order_count_raw_domain_matches_statut_contract(statut, expected_states):
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [{"__count": 1}]
        token = odoo_uid_ctx.set(1)
        try:
            get_order_count_raw(client="", periode="", statut=statut)
        finally:
            odoo_uid_ctx.reset(token)

    called_domain = mock_read_group.call_args.kwargs["domain"]
    assert called_domain == [("state", "in", expected_states)]


def test_get_order_count_raw_unknown_statut_falls_back_to_toutes_domain():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [{"__count": 1}]
        token = odoo_uid_ctx.set(1)
        try:
            get_order_count_raw(client="", periode="", statut="n'importe quoi")
        finally:
            odoo_uid_ctx.reset(token)

    called_domain = mock_read_group.call_args.kwargs["domain"]
    assert called_domain == [("state", "in", ["draft", "sent", "sale", "done"])]


@pytest.mark.parametrize("statut", ["toutes", "confirmees", "brouillon", "annulees"])
def test_get_order_count_and_get_total_sales_share_identical_domain_per_statut(statut):
    """Cross-tool guarantee: 'combien de commandes' and 'quel montant'
    must agree on the same domain for a given statut, since both route
    through the single _resolve_statut() source of truth."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_rg_count:
        mock_rg_count.return_value = [{"__count": 1}]
        token = odoo_uid_ctx.set(1)
        try:
            get_order_count_raw(client="", periode="", statut=statut)
        finally:
            odoo_uid_ctx.reset(token)
        count_domain = mock_rg_count.call_args.kwargs["domain"]

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
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group, \
         patch("erp_data._odoo_helpers.parse_period") as mock_parse_period:
        mock_parse_period.return_value = ("2026-08-01", "2026-08-31")
        mock_read_group.return_value = [{"__count": 7}]
        token = odoo_uid_ctx.set(1)
        try:
            get_order_count_raw(client="", periode="le mois dernier", statut="toutes")
        finally:
            odoo_uid_ctx.reset(token)

    called_domain = mock_read_group.call_args.kwargs["domain"]
    assert ("date_order", ">=", "2026-08-01") in called_domain
    assert ("date_order", "<=", "2026-08-31 23:59:59") in called_domain
