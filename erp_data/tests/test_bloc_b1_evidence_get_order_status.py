"""
erp_data/tests/test_bloc_b1_evidence_get_order_status.py

B1 replication of the B0 pilot pattern to a fourth ORM tool (ORM 3/9, todo/
contexte.txt sections 470+). Validates that get_order_status_raw()
produces structured Evidence at the source, mirroring
test_bloc_b1_evidence_get_product_stock.py's coverage of
get_product_stock_raw. Pure unit tests -- connector.search_read is mocked
so these never touch a live Odoo instance, unlike the existing
@pytest.mark.integration tests in test_odoo_tools.py.

First ORM tool Evidence-ified whose underlying query is a single-record
search_read lookup rather than a read_group aggregation, producing a
qualitative fact (order state) rather than a numeric sum.
"""

from unittest.mock import patch

from erp_data.tools.inventory import (
    get_order_status_raw,
    get_order_status,
)
from erp_data.odoo_context import odoo_uid_ctx
from core.evidence import Evidence, EvidenceSourceType


def test_get_order_status_raw_returns_text_and_two_evidence():
    with patch("erp_data._odoo_helpers.connector.search_read") as mock_search_read:
        mock_search_read.return_value = [
            {"state": "sale", "amount_total": 999.0, "partner_id": [1, "Rakoto"]}
        ]
        token = odoo_uid_ctx.set(7)
        try:
            text, evidence_list = get_order_status_raw("S00042")
        finally:
            odoo_uid_ctx.reset(token)

    assert isinstance(text, str)
    assert "Rakoto" in text
    assert "Bon de commande (Confirmé)" in text
    assert isinstance(evidence_list, list)
    assert len(evidence_list) == 2
    for e in evidence_list:
        assert isinstance(e, Evidence)
        assert e.source_type == EvidenceSourceType.ORM
        assert e.source == "sale.order:search_read(state,partner_id)"


def test_get_order_status_raw_evidence_carries_raw_state_not_french_label():
    """The Evidence must carry Odoo's own raw state value (e.g. "sale"),
    not the display-only French translation (state_fr) -- the translation
    is a rendering of the same fact, not an independent one."""
    with patch("erp_data._odoo_helpers.connector.search_read") as mock_search_read:
        mock_search_read.return_value = [
            {"state": "sale", "amount_total": 999.0, "partner_id": [1, "Rakoto"]}
        ]
        token = odoo_uid_ctx.set(1)
        try:
            _text, evidence_list = get_order_status_raw("S00042")
        finally:
            odoo_uid_ctx.reset(token)

    state_evidence = evidence_list[0]
    assert state_evidence.value == "sale"
    assert "Bon de commande" not in str(state_evidence.value)
    assert "Order state" in state_evidence.claim


def test_get_order_status_raw_evidence_covers_partner_separately():
    with patch("erp_data._odoo_helpers.connector.search_read") as mock_search_read:
        mock_search_read.return_value = [
            {"state": "draft", "amount_total": 100.0, "partner_id": [2, "Randria"]}
        ]
        token = odoo_uid_ctx.set(1)
        try:
            _text, evidence_list = get_order_status_raw("S00099")
        finally:
            odoo_uid_ctx.reset(token)

    partner_evidence = evidence_list[1]
    assert partner_evidence.value == "Randria"
    assert "Partner" in partner_evidence.claim


def test_get_order_status_raw_never_asserts_amount_total_as_evidence():
    """amount_total is fetched by the query but never displayed in text --
    no Evidence must be fabricated for a fact the text never asserts."""
    with patch("erp_data._odoo_helpers.connector.search_read") as mock_search_read:
        mock_search_read.return_value = [
            {"state": "sale", "amount_total": 12345.67, "partner_id": [1, "Rakoto"]}
        ]
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_order_status_raw("S00042")
        finally:
            odoo_uid_ctx.reset(token)

    assert "12345.67" not in text
    assert all(e.value != 12345.67 for e in evidence_list)


def test_get_order_status_raw_empty_result_produces_single_negative_evidence():
    """Even a 'order not found' outcome is itself a fact worth recording
    as Evidence (absence of a match), not just silently dropped -- same
    convention already established by the read_group-based ORM tools."""
    with patch("erp_data._odoo_helpers.connector.search_read") as mock_search_read:
        mock_search_read.return_value = []
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_order_status_raw("S99999")
        finally:
            odoo_uid_ctx.reset(token)

    assert "n'existe pas" in text
    assert len(evidence_list) == 1
    evidence = evidence_list[0]
    assert evidence.value is None
    assert evidence.source_type == EvidenceSourceType.ORM
    assert evidence.claim == "No sale.order matches name=S99999"


def test_get_order_status_raw_multiple_results_only_covers_results_zero():
    """Defensive discipline mirroring get_product_stock_raw: even though
    an exact name match should return at most one record in practice, if
    more than one is ever returned, only results[0] is reflected -- the
    Evidence must never cover the ignored entries either."""
    with patch("erp_data._odoo_helpers.connector.search_read") as mock_search_read:
        mock_search_read.return_value = [
            {"state": "draft", "amount_total": 10.0, "partner_id": [1, "A"]},
            {"state": "cancel", "amount_total": 999.0, "partner_id": [2, "B"]},
        ]
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_order_status_raw("S1")
        finally:
            odoo_uid_ctx.reset(token)

    assert "B" not in text
    assert len(evidence_list) == 2
    assert evidence_list[0].value == "draft"
    assert evidence_list[1].value == "A"
    assert all(e.value not in ("cancel", "B") for e in evidence_list)


def test_get_order_status_raw_no_confidence_set():
    """B0 decision (todo/contexte.txt section 426): a deterministic ORM
    read never carries a confidence score."""
    with patch("erp_data._odoo_helpers.connector.search_read") as mock_search_read:
        mock_search_read.return_value = [
            {"state": "sale", "amount_total": 1.0, "partner_id": [1, "X"]}
        ]
        token = odoo_uid_ctx.set(1)
        try:
            _text, evidence_list = get_order_status_raw("S1")
        finally:
            odoo_uid_ctx.reset(token)

    assert all(e.confidence is None for e in evidence_list)


def test_get_order_status_raw_evidence_scope_carries_execution_identity():
    with patch("erp_data._odoo_helpers.connector.search_read") as mock_search_read:
        mock_search_read.return_value = [
            {"state": "sale", "amount_total": 1.0, "partner_id": [1, "X"]}
        ]
        token = odoo_uid_ctx.set(42)
        try:
            _text, evidence_list = get_order_status_raw("S1")
        finally:
            odoo_uid_ctx.reset(token)

    for e in evidence_list:
        assert e.scope["execution_identity"] == 42
        assert "read_at" in e.scope
        assert "company_id" not in e.scope  # not fabricated, see _orm_evidence_scope


def test_get_order_status_tool_wrapper_unchanged_return_contract():
    """The @tool wrapper must still return a plain string."""
    with patch("erp_data._odoo_helpers.connector.search_read") as mock_search_read:
        mock_search_read.return_value = [
            {"state": "sale", "amount_total": 1.0, "partner_id": [1, "X"]}
        ]
        token = odoo_uid_ctx.set(1)
        try:
            result = get_order_status.invoke({"reference": "S1"})
        finally:
            odoo_uid_ctx.reset(token)

    assert isinstance(result, str)
    assert "X" in result


def test_get_order_status_tool_wrapper_still_catches_connector_exceptions():
    """Non-regression of the original try/except: it lives in the @tool
    wrapper, not in _raw -- the observable error-string behavior on a
    connector failure must be identical to before this Evidence-ification."""
    with patch("erp_data._odoo_helpers.connector.search_read") as mock_search_read:
        mock_search_read.side_effect = RuntimeError("boom")
        token = odoo_uid_ctx.set(1)
        try:
            result = get_order_status.invoke({"reference": "S1"})
        finally:
            odoo_uid_ctx.reset(token)

    assert "Erreur lors de la récupération de la commande" in result


def test_get_order_status_raw_propagates_exceptions_without_fabricating_evidence():
    """_raw must never swallow a connector exception itself -- doing so
    would risk fabricating an Evidence (e.g. a false negative) from a
    technical failure rather than a real absence of data."""
    with patch("erp_data._odoo_helpers.connector.search_read") as mock_search_read:
        mock_search_read.side_effect = RuntimeError("boom")
        token = odoo_uid_ctx.set(1)
        try:
            raised = False
            try:
                get_order_status_raw("S1")
            except RuntimeError:
                raised = True
        finally:
            odoo_uid_ctx.reset(token)

    assert raised
