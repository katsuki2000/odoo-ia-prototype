"""
erp_data/tests/test_bloc_b1_evidence_get_product_stock.py

B1 replication of the B0 pilot pattern to a third ORM tool (ORM 2/9, todo/
contexte.txt sections 468+). Validates that get_product_stock_raw()
produces structured Evidence at the source, mirroring
test_bloc_b1_evidence_get_average_sales.py's coverage of
get_average_sales_raw. Pure unit tests -- connector.read_group is mocked
so these never touch a live Odoo instance, unlike the existing
@pytest.mark.integration tests in test_odoo_tools.py.

Unlike get_total_sales_raw/get_average_sales_raw (single Evidence),
get_product_stock_raw returns a List[Evidence]: quantity and
reserved_quantity are two independent raw facts from the same read_group
call, each worth its own Evidence. The displayed `available` figure is a
derived subtraction, never asserted as its own Evidence.
"""

from unittest.mock import patch

from erp_data.tools.inventory import (
    get_product_stock_raw,
    get_product_stock,
)
from erp_data.odoo_context import odoo_uid_ctx
from core.evidence.evidence import Evidence, EvidenceSourceType


def test_get_product_stock_raw_returns_text_and_two_evidence():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [
            {"quantity": 100.0, "reserved_quantity": 30.0, "product_id": [1, "Widget"]}
        ]
        token = odoo_uid_ctx.set(7)
        try:
            text, evidence_list = get_product_stock_raw("Widget")
        finally:
            odoo_uid_ctx.reset(token)

    assert isinstance(text, str)
    assert "70.0" in text  # available = quantity - reserved
    assert "100.0" in text
    assert "30.0" in text
    assert isinstance(evidence_list, list)
    assert len(evidence_list) == 2
    for e in evidence_list:
        assert isinstance(e, Evidence)
        assert e.source_type == EvidenceSourceType.ORM
        assert e.source == (
            "stock.quant:read_group(quantity:sum,reserved_quantity:sum, "
            "location_id.usage=internal)"
        )


def test_get_product_stock_raw_evidence_covers_quantity_and_reserved_separately():
    """quantity and reserved_quantity are each an independent raw fact --
    available is arithmetic on those facts, not a third Evidence."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [
            {"quantity": 100.0, "reserved_quantity": 30.0, "product_id": [1, "Widget"]}
        ]
        token = odoo_uid_ctx.set(1)
        try:
            _text, evidence_list = get_product_stock_raw("Widget")
        finally:
            odoo_uid_ctx.reset(token)

    qty_evidence = evidence_list[0]
    reserved_evidence = evidence_list[1]
    assert qty_evidence.value == 100.0
    assert "Total quantity" in qty_evidence.claim
    assert reserved_evidence.value == 30.0
    assert "Reserved quantity" in reserved_evidence.claim
    # available (70.0) never asserted as its own Evidence value
    assert all(e.value != 70.0 for e in evidence_list)


def test_get_product_stock_raw_empty_result_produces_single_negative_evidence():
    """Even a 'no data found' outcome is itself a fact worth recording as
    Evidence (absence of a match), not just silently dropped -- same
    convention already established by get_total_sales_raw/
    get_average_sales_raw. Exactly one negative Evidence, not two."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = []
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_product_stock_raw("Inconnu")
        finally:
            odoo_uid_ctx.reset(token)

    assert "n'a pas été trouvé" in text
    assert len(evidence_list) == 1
    evidence = evidence_list[0]
    assert evidence.value is None
    assert evidence.source_type == EvidenceSourceType.ORM
    assert evidence.claim == "No internal stock.quant matches product=Inconnu"
    assert "location_id.usage=internal" in evidence.source


def test_get_product_stock_raw_multiple_products_returns_ambiguity():
    """Partial product names must not silently select the first match."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [
            {"quantity": 10.0, "reserved_quantity": 2.0, "product_id": [1, "Widget A"]},
            {"quantity": 999.0, "reserved_quantity": 999.0, "product_id": [2, "Widget B"]},
        ]
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_product_stock_raw("Widget")
        finally:
            odoo_uid_ctx.reset(token)

    assert "AMBIGUÏTÉ" in text
    assert "Widget A" in text and "Widget B" in text
    assert evidence_list == []
    assert mock_read_group.call_args.kwargs["domain"] == [
        ("product_id.name", "ilike", "Widget"),
        ("location_id.usage", "=", "internal"),
    ]


def test_get_product_stock_raw_no_confidence_set():
    """B0 decision (todo/contexte.txt section 426): a deterministic ORM
    read never carries a confidence score."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [
            {"quantity": 5.0, "reserved_quantity": 1.0, "product_id": [1, "X"]}
        ]
        token = odoo_uid_ctx.set(1)
        try:
            _text, evidence_list = get_product_stock_raw("X")
        finally:
            odoo_uid_ctx.reset(token)

    assert all(e.confidence is None for e in evidence_list)


def test_get_product_stock_raw_evidence_scope_carries_execution_identity():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [
            {"quantity": 5.0, "reserved_quantity": 1.0, "product_id": [1, "X"]}
        ]
        token = odoo_uid_ctx.set(42)
        try:
            _text, evidence_list = get_product_stock_raw("X")
        finally:
            odoo_uid_ctx.reset(token)

    for e in evidence_list:
        assert e.scope["execution_identity"] == 42
        assert "read_at" in e.scope
        assert "company_id" not in e.scope  # not fabricated, see _orm_evidence_scope


def test_get_product_stock_tool_wrapper_unchanged_return_contract():
    """The @tool wrapper must still return a plain string."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [
            {"quantity": 5.0, "reserved_quantity": 1.0, "product_id": [1, "X"]}
        ]
        token = odoo_uid_ctx.set(1)
        try:
            result = get_product_stock.invoke({"produit": "X"})
        finally:
            odoo_uid_ctx.reset(token)

    assert isinstance(result, str)
    assert "4.0" in result  # available = 5.0 - 1.0


def test_get_product_stock_tool_wrapper_still_catches_connector_exceptions():
    """Non-regression of the original try/except: it lives in the @tool
    wrapper, not in _raw -- the observable error-string behavior on a
    connector failure must be identical to before this Evidence-ification."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.side_effect = RuntimeError("boom")
        token = odoo_uid_ctx.set(1)
        try:
            result = get_product_stock.invoke({"produit": "X"})
        finally:
            odoo_uid_ctx.reset(token)

    assert "Erreur lors de la vérification du stock" in result


def test_get_product_stock_raw_propagates_exceptions_without_fabricating_evidence():
    """_raw must never swallow a connector exception itself -- doing so
    would risk fabricating an Evidence (e.g. a false negative) from a
    technical failure rather than a real absence of data."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.side_effect = RuntimeError("boom")
        token = odoo_uid_ctx.set(1)
        try:
            raised = False
            try:
                get_product_stock_raw("X")
            except RuntimeError:
                raised = True
        finally:
            odoo_uid_ctx.reset(token)

    assert raised
