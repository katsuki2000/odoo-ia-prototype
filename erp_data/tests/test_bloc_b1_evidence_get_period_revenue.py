"""
erp_data/tests/test_bloc_b1_evidence_get_period_revenue.py

B1 replication of the B0 pilot pattern to the ninth and last ORM tool
(ORM 9/9, todo/contexte.txt section 478+). Validates that
get_period_revenue_raw() produces structured Evidence at the source,
mirroring the conventions of test_bloc_b1_evidence_get_total_invoices.py.
Pure unit tests -- connector.read_group is mocked so these never touch a
live Odoo instance.

Revenue is read only from paid invoices in account.move. Sales orders are
not a semantic fallback for paid invoice revenue. Amounts are grouped by
currency and each currency has separate Evidence.
"""

from unittest.mock import patch

from erp_data.tools.accounting import (
    get_period_revenue_raw,
    get_period_revenue,
)
from erp_data.odoo_context import odoo_uid_ctx
from core.evidence.evidence import Evidence, EvidenceSourceType


def test_full_branch_keeps_currency_totals_and_evidence_separate():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_rg:
        mock_rg.return_value = [
            {"currency_id": [1, "EUR"], "amount_total": 100.0},
            {"currency_id": [2, "USD"], "amount_total": 250.0},
        ]
        token = odoo_uid_ctx.set(7)
        try:
            text, evidence_list = get_period_revenue_raw("2025")
        finally:
            odoo_uid_ctx.reset(token)

    assert "100.00 EUR" in text and "250.00 USD" in text
    assert len(evidence_list) == 2
    assert all(isinstance(e, Evidence) for e in evidence_list)
    assert all(e.source_type == EvidenceSourceType.ORM for e in evidence_list)
    assert all(
        e.source == "account.move:read_group(amount_total:sum, groupby=currency_id)"
        for e in evidence_list
    )
    assert {e.value["currency"]: e.value["amount"] for e in evidence_list} == {
        "EUR": 100.0, "USD": 250.0,
    }


def test_single_currency_branch_evidence():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_rg:
        mock_rg.return_value = [
            {"currency_id": [1, "MGA"], "amount_total": 999.0},
        ]
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_period_revenue_raw("toutes")
        finally:
            odoo_uid_ctx.reset(token)

    assert "999.00" in text
    assert len(evidence_list) == 1
    e = evidence_list[0]
    assert e.source == "account.move:read_group(amount_total:sum, groupby=currency_id)"
    assert e.value == {"currency": "MGA", "amount": 999.0}
    assert "toutes" in e.claim


def test_revenue_does_not_fall_back_to_uninvoiced_sales_orders():
    """Sales orders are not proof of paid invoice revenue."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_rg:
        mock_rg.return_value = []
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_period_revenue_raw("ce mois")
        finally:
            odoo_uid_ctx.reset(token)

    assert "Aucun chiffre d'affaires" in text
    assert mock_rg.call_count == 1
    assert mock_rg.call_args.kwargs["model"] == "account.move"
    assert len(evidence_list) == 1
    e = evidence_list[0]
    assert e.source.endswith("[empty]")
    assert "sale.order" not in e.source
    assert e.value is None


def test_empty_branch_negative_evidence_covers_the_invoice_read():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_rg:
        mock_rg.return_value = []
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_period_revenue_raw("2024")
        finally:
            odoo_uid_ctx.reset(token)

    assert "2024" in text
    assert len(evidence_list) == 1
    e = evidence_list[0]
    assert e.value is None
    assert "account.move" in e.source and "sale.order" not in e.source
    assert "[empty]" in e.source
    assert e.claim == "No matching invoice revenue found for period=2024"


def test_no_confidence_ever_set():
    """B0 decision (core/evidence.py): a deterministic ORM read never
    carries a confidence score, across every branch."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_rg:
        mock_rg.return_value = [{"currency_id": [1, "MGA"], "amount_total": 1.0}]
        token = odoo_uid_ctx.set(1)
        try:
            _text, evidence_list = get_period_revenue_raw("toutes")
        finally:
            odoo_uid_ctx.reset(token)

    assert all(e.confidence is None for e in evidence_list)


def test_evidence_scope_carries_execution_identity_not_company_id():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_rg:
        mock_rg.return_value = [{"currency_id": [1, "MGA"], "amount_total": 1.0}]
        token = odoo_uid_ctx.set(42)
        try:
            _text, evidence_list = get_period_revenue_raw("toutes")
        finally:
            odoo_uid_ctx.reset(token)

    for e in evidence_list:
        assert e.scope["execution_identity"] == 42
        assert "read_at" in e.scope
        assert "company_id" not in e.scope


def test_tool_wrapper_unchanged_return_contract():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_rg:
        mock_rg.return_value = [{"currency_id": [1, "MGA"], "amount_total": 1.0}]
        token = odoo_uid_ctx.set(1)
        try:
            result = get_period_revenue.invoke({"periode": "toutes"})
        finally:
            odoo_uid_ctx.reset(token)

    assert isinstance(result, str)


def test_tool_wrapper_still_catches_connector_exceptions():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_rg:
        mock_rg.side_effect = RuntimeError("boom")
        token = odoo_uid_ctx.set(1)
        try:
            result = get_period_revenue.invoke({"periode": "toutes"})
        finally:
            odoo_uid_ctx.reset(token)

    assert "Erreur lors du calcul du CA" in result


def test_raw_propagates_exceptions_without_fabricating_evidence():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_rg:
        mock_rg.side_effect = RuntimeError("boom")
        token = odoo_uid_ctx.set(1)
        try:
            raised = False
            try:
                get_period_revenue_raw("toutes")
            except RuntimeError:
                raised = True
        finally:
            odoo_uid_ctx.reset(token)

    assert raised
