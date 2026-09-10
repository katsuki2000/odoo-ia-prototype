"""
erp_data/tests/test_bloc_b1_evidence_get_total_invoices.py

B1 replication of the B0 pilot pattern to the eighth ORM tool (ORM 8/9,
todo/contexte.txt section 478+). Validates that get_total_invoices_raw()
produces structured Evidence at the source, mirroring the conventions of
test_bloc_b1_evidence_get_order_status.py / test_bloc_b1_evidence_
get_recent_tickets.py. Pure unit tests -- connector.read_group is mocked
so these never touch a live Odoo instance.

First ORM tool whose Evidence-ification spans a two-model fallback
(account.move -> sale.order) rather than a single model -- the ORM 8/9
decision table (agreed with Trunk) is the primary thing under test here:
1 Evidence for the global sum branch (Python sum() over N read_group rows
is the calculation method for a single asserted fact, not N facts), 1 for
the client-specific branch, [] for AMBIGUITE (no total is ever presented),
1 sourced from sale.order for the fallback branch (source follows real
provenance, not what the text renders), and 1 negative Evidence with a
COMPOSITE source (both account.move and sale.order attempts) for the
fully-empty branch -- never sourced from account.move alone.
"""

from unittest.mock import patch

from erp_data.tools.accounting import (
    get_total_invoices_raw,
    get_total_invoices,
)
from erp_data.odoo_context import odoo_uid_ctx
from core.evidence.evidence import Evidence, EvidenceSourceType


def test_global_branch_sums_rows_into_single_evidence():
    """N read_group rows (one per partner) still produce exactly 1
    Evidence -- the Python sum() is the calculation method for the single
    'total' fact the text actually asserts, not a fact-per-row."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_rg:
        mock_rg.return_value = [
            {"partner_id": [1, "Rakoto"], "amount_total": 100.0},
            {"partner_id": [2, "Randria"], "amount_total": 250.0},
        ]
        token = odoo_uid_ctx.set(7)
        try:
            text, evidence_list = get_total_invoices_raw("", "toutes")
        finally:
            odoo_uid_ctx.reset(token)

    assert "350.00" in text
    assert len(evidence_list) == 1
    e = evidence_list[0]
    assert isinstance(e, Evidence)
    assert e.source_type == EvidenceSourceType.ORM
    assert e.source == "account.move:read_group(amount_total:sum, groupby=partner_id)"
    assert e.value == 350.0


def test_client_specific_branch_single_result_evidence():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_rg:
        mock_rg.return_value = [
            {"partner_id": [1, "Rakoto"], "amount_total": 999.0},
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
    assert e.source == "account.move:read_group(amount_total:sum, groupby=partner_id)"
    assert e.value == 999.0
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


def test_sale_order_fallback_branch_sources_from_sale_order_not_account_move():
    """The value's real provenance is sale.order -- Evidence.source must
    reflect that, never account.move, even though the text prose does not
    currently render a '[Source: ...]' suffix on this branch."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_rg:
        mock_rg.side_effect = [
            [],  # account.move: empty
            [{"amount_total": 5000.0}],  # sale.order fallback: found
        ]
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_total_invoices_raw("", "toutes")
        finally:
            odoo_uid_ctx.reset(token)

    assert "5000.00" in text
    assert len(evidence_list) == 1
    e = evidence_list[0]
    assert e.source == "sale.order:read_group(amount_total:sum)"
    assert "account.move" not in e.source
    assert e.value == 5000.0


def test_fully_empty_branch_negative_evidence_has_composite_source():
    """When BOTH account.move and the sale.order fallback return nothing,
    the negative Evidence's source must cover both attempted reads -- not
    account.move alone, which would misrepresent what was actually
    checked (the sale.order attempt is real, even if the text never
    surfaces it as its own fact)."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_rg:
        mock_rg.side_effect = [
            [],  # account.move: empty
            [],  # sale.order fallback: also empty
        ]
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_total_invoices_raw("Andria", "impayé")
        finally:
            odoo_uid_ctx.reset(token)

    assert "Andria" in text
    assert len(evidence_list) == 1
    e = evidence_list[0]
    assert e.value is None
    assert "account.move" in e.source and "sale.order" in e.source
    assert "[empty]" in e.source
    assert e.claim == "No matching invoice/sale amount found for client=Andria, statut=impayé"


def test_fully_empty_branch_no_separate_negative_evidence_for_sale_order():
    """Only 1 Evidence total on this branch -- no second, standalone
    negative Evidence for the sale.order attempt on its own, since the
    final text never surfaces that attempt as a distinct fact."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_rg:
        mock_rg.side_effect = [[], []]
        token = odoo_uid_ctx.set(1)
        try:
            _text, evidence_list = get_total_invoices_raw("", "toutes")
        finally:
            odoo_uid_ctx.reset(token)

    assert len(evidence_list) == 1


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
