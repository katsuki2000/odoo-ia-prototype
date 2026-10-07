"""
erp_data/tests/test_bloc_b1_evidence_get_total_invoices.py

B1 replication of the B0 pilot pattern to the eighth ORM tool (ORM 8/9,
todo/contexte.txt section 478+). Validates that get_total_invoices_raw()
produces structured Evidence at the source, mirroring the conventions of
test_bloc_b1_evidence_get_order_status.py / test_bloc_b1_evidence_
get_recent_tickets.py. Pure unit tests -- connector.read_group is mocked
so these never touch a live Odoo instance.

Invoice totals are read only from account.move; sale.order is not a
semantic fallback for invoice data. Aggregated amounts are grouped by
currency and each currency has separate Evidence. Ambiguous client matches
produce no asserted total and no Evidence.
"""

from unittest.mock import patch

from erp_data.tools.accounting import (
    get_total_invoices_raw,
    get_total_invoices,
)
from erp_data.odoo_context import odoo_uid_ctx
from core.evidence.evidence import Evidence, EvidenceSourceType


def test_global_branch_keeps_currency_totals_and_evidence_separate():
    """Rows are totaled independently for each currency.
    Each currency total has its own Evidence."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_rg:
        mock_rg.return_value = [
            {"partner_id": [1, "Rakoto"], "amount_total": 100.0, "currency_id": [1, "EUR"]},
            {"partner_id": [2, "Randria"], "amount_total": 250.0, "currency_id": [2, "USD"]},
        ]
        token = odoo_uid_ctx.set(7)
        try:
            text, evidence_list = get_total_invoices_raw("", "toutes")
        finally:
            odoo_uid_ctx.reset(token)

    assert "100.00 EUR" in text and "250.00 USD" in text
    assert len(evidence_list) == 2
    assert all(isinstance(e, Evidence) for e in evidence_list)
    assert all(e.source_type == EvidenceSourceType.ORM for e in evidence_list)
    assert all(
        e.source == "account.move:read_group(amount_total:sum, groupby=partner_id,currency_id)"
        for e in evidence_list
    )
    assert {e.value["currency"]: e.value["amount"] for e in evidence_list} == {
        "EUR": 100.0, "USD": 250.0,
    }
    assert mock_rg.call_args.kwargs["groupby"] == ["partner_id", "currency_id"]
    assert mock_rg.call_args.kwargs["lazy"] is False


def test_client_specific_branch_single_result_evidence():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_rg:
        mock_rg.return_value = [
            {"partner_id": [1, "Rakoto"], "amount_total": 999.0, "currency_id": [1, "MGA"]},
        ]
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_total_invoices_raw("Rakoto", "payé")
        finally:
            odoo_uid_ctx.reset(token)

    assert "Rakoto" in text
    assert "999.00" in text
    assert len(evidence_list) == 1
    e = evidence_list[0]
    assert e.source == "account.move:read_group(amount_total:sum, groupby=partner_id,currency_id)"
    assert e.value == {"currency": "MGA", "amount": 999.0}
    assert "Rakoto" in e.claim


def test_ambiguite_branch_produces_no_evidence():
    """No total is ever presented to the user on this branch -- an
    Evidence here would assert a fact the text never actually states."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_rg:
        mock_rg.return_value = [
            {"partner_id": [1, "Rakoto Jean"], "amount_total": 100.0},
            {"partner_id": [2, "Rakoto Paul"], "amount_total": 200.0},
        ]
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_total_invoices_raw("Rakoto", "toutes")
        finally:
            odoo_uid_ctx.reset(token)

    assert "AMBIGUÏTÉ" in text
    assert evidence_list == []


def test_no_invoice_results_do_not_fall_back_to_sales_orders():
    """Sales orders are not invoices and cannot prove invoice totals."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_rg:
        mock_rg.return_value = []
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_total_invoices_raw("", "toutes")
        finally:
            odoo_uid_ctx.reset(token)

    assert "Aucune facture" in text
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
            text, evidence_list = get_total_invoices_raw("Andria", "impayé")
        finally:
            odoo_uid_ctx.reset(token)

    assert "Andria" in text
    assert len(evidence_list) == 1
    e = evidence_list[0]
    assert e.value is None
    assert "account.move" in e.source and "sale.order" not in e.source
    assert "[empty]" in e.source
    assert e.claim == "No matching invoice amount found for client=Andria, statut=impayé"


def test_no_confidence_ever_set():
    """B0 decision (core/evidence.py): a deterministic ORM read never
    carries a confidence score, across every branch."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_rg:
        mock_rg.return_value = [{"partner_id": [1, "X"], "amount_total": 1.0}]
        token = odoo_uid_ctx.set(1)
        try:
            _text, evidence_list = get_total_invoices_raw("", "toutes")
        finally:
            odoo_uid_ctx.reset(token)

    assert all(e.confidence is None for e in evidence_list)


def test_evidence_scope_carries_execution_identity_not_company_id():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_rg:
        mock_rg.return_value = [{"partner_id": [1, "X"], "amount_total": 1.0}]
        token = odoo_uid_ctx.set(42)
        try:
            _text, evidence_list = get_total_invoices_raw("", "toutes")
        finally:
            odoo_uid_ctx.reset(token)

    for e in evidence_list:
        assert e.scope["execution_identity"] == 42
        assert "read_at" in e.scope
        assert "company_id" not in e.scope


def test_tool_wrapper_unchanged_return_contract():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_rg:
        mock_rg.return_value = [{"partner_id": [1, "X"], "amount_total": 1.0}]
        token = odoo_uid_ctx.set(1)
        try:
            result = get_total_invoices.invoke({"client": "", "statut": "toutes"})
        finally:
            odoo_uid_ctx.reset(token)

    assert isinstance(result, str)


def test_tool_wrapper_still_catches_connector_exceptions():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_rg:
        mock_rg.side_effect = RuntimeError("boom")
        token = odoo_uid_ctx.set(1)
        try:
            result = get_total_invoices.invoke({"client": "", "statut": "toutes"})
        finally:
            odoo_uid_ctx.reset(token)

    assert "Erreur lors de la récupération des factures" in result


def test_raw_propagates_exceptions_without_fabricating_evidence():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_rg:
        mock_rg.side_effect = RuntimeError("boom")
        token = odoo_uid_ctx.set(1)
        try:
            raised = False
            try:
                get_total_invoices_raw("", "toutes")
            except RuntimeError:
                raised = True
        finally:
            odoo_uid_ctx.reset(token)

    assert raised
