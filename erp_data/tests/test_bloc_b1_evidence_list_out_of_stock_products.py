"""
erp_data/tests/test_bloc_b1_evidence_list_out_of_stock_products.py

B1 replication of the B0 pilot pattern to a sixth ORM tool (ORM 5/9, todo/
contexte.txt sections 473+). Validates that
list_out_of_stock_products_raw() produces structured Evidence at the
source, mirroring test_bloc_b1_evidence_search_partner.py's coverage of
search_partner_raw. Pure unit tests -- connector.read_group is mocked so
these never touch a live Odoo instance.

Structurally new relative to the previous 4 ORM tools: read_group here is
unfiltered (domain=[]) and returns every product -- the quantity<=0
criterion is applied in Python. So a "no rupture" outcome is not a
negative/empty-query-result fact (unlike every other ORM tool's empty
case) -- it's a positive fact (value=0) that the query succeeded and
zero products satisfy the criterion.
"""

from unittest.mock import patch

from erp_data.tools.inventory import (
    list_out_of_stock_products_raw,
    list_out_of_stock_products,
)
from erp_data.odoo_context import odoo_uid_ctx
from core.evidence import Evidence, EvidenceSourceType


def test_list_out_of_stock_raw_returns_text_and_one_evidence_per_product():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [
            {"product_id": [1, "Chaise"], "quantity": 0.0},
            {"product_id": [2, "Table"], "quantity": -2.0},
            {"product_id": [3, "Lampe"], "quantity": 15.0},
        ]
        token = odoo_uid_ctx.set(7)
        try:
            text, evidence_list = list_out_of_stock_products_raw()
        finally:
            odoo_uid_ctx.reset(token)

    assert "Chaise" in text
    assert "Table" in text
    assert "Lampe" not in text
    assert isinstance(evidence_list, list)
    assert len(evidence_list) == 2
    for e in evidence_list:
        assert isinstance(e, Evidence)
        assert e.source_type == EvidenceSourceType.ORM
        assert e.source == "stock.quant:read_group(quantity:sum)"


def test_list_out_of_stock_raw_evidence_value_carries_actual_quantity():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [
            {"product_id": [1, "Chaise"], "quantity": 0.0},
            {"product_id": [2, "Table"], "quantity": -2.0},
        ]
        token = odoo_uid_ctx.set(1)
        try:
            _text, evidence_list = list_out_of_stock_products_raw()
        finally:
            odoo_uid_ctx.reset(token)

    values = {e.claim: e.value for e in evidence_list}
    assert values["Product Chaise is out of stock (quantity<=0)"] == 0.0
    assert values["Product Table is out of stock (quantity<=0)"] == -2.0


def test_list_out_of_stock_raw_no_rupture_produces_single_positive_evidence():
    """Design confirmed by San Goku (section 473): unlike every other ORM
    tool's empty case, "zero rupture products" is a positive fact (the
    query succeeded, nothing matched quantity<=0) -- value=0, not None."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [
            {"product_id": [1, "Chaise"], "quantity": 15.0},
        ]
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = list_out_of_stock_products_raw()
        finally:
            odoo_uid_ctx.reset(token)

    assert "Aucun produit" in text
    assert len(evidence_list) == 1
    evidence = evidence_list[0]
    assert evidence.value == 0
    assert evidence.value is not None
    assert evidence.claim == "No stock.quant product has quantity<=0"


def test_list_out_of_stock_raw_more_than_ten_only_first_ten_get_evidence():
    """Pre-existing display truncation to 10 is unchanged -- the Evidence
    list must never cover a rupture product beyond that truncation, since
    text never asserts anything about the ignored ones."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [
            {"product_id": [i, f"P{i}"], "quantity": -1.0} for i in range(15)
        ]
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = list_out_of_stock_products_raw()
        finally:
            odoo_uid_ctx.reset(token)

    assert len(evidence_list) == 10
    assert text.endswith("...")
    assert all("P14" not in e.claim and "P10" not in e.claim for e in evidence_list)


def test_list_out_of_stock_raw_no_confidence_set():
    """B0 decision (todo/contexte.txt section 426): a deterministic ORM
    read never carries a confidence score."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [
            {"product_id": [1, "X"], "quantity": -1.0},
        ]
        token = odoo_uid_ctx.set(1)
        try:
            _text, evidence_list = list_out_of_stock_products_raw()
        finally:
            odoo_uid_ctx.reset(token)

    assert all(e.confidence is None for e in evidence_list)


def test_list_out_of_stock_raw_evidence_scope_carries_execution_identity():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [
            {"product_id": [1, "X"], "quantity": -1.0},
        ]
        token = odoo_uid_ctx.set(42)
        try:
            _text, evidence_list = list_out_of_stock_products_raw()
        finally:
            odoo_uid_ctx.reset(token)

    for e in evidence_list:
        assert e.scope["execution_identity"] == 42
        assert "read_at" in e.scope
        assert "company_id" not in e.scope  # not fabricated, see _orm_evidence_scope


def test_list_out_of_stock_tool_wrapper_unchanged_return_contract():
    """The @tool wrapper must still return a plain string."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [
            {"product_id": [1, "X"], "quantity": -1.0},
        ]
        token = odoo_uid_ctx.set(1)
        try:
            result = list_out_of_stock_products.invoke({})
        finally:
            odoo_uid_ctx.reset(token)

    assert isinstance(result, str)
    assert "X" in result


def test_list_out_of_stock_tool_wrapper_still_catches_connector_exceptions():
    """Non-regression of the original try/except: it lives in the @tool
    wrapper, not in _raw -- the observable error-string behavior on a
    connector failure must be identical to before this Evidence-ification."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.side_effect = RuntimeError("boom")
        token = odoo_uid_ctx.set(1)
        try:
            result = list_out_of_stock_products.invoke({})
        finally:
            odoo_uid_ctx.reset(token)

    assert "Erreur lors de la récupération des stocks" in result


def test_list_out_of_stock_raw_propagates_exceptions_without_fabricating_evidence():
    """_raw must never swallow a connector exception itself -- doing so
    would risk fabricating an Evidence (e.g. a false "no rupture") from a
    technical failure rather than a real absence of rupture."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.side_effect = RuntimeError("boom")
        token = odoo_uid_ctx.set(1)
        try:
            raised = False
            try:
                list_out_of_stock_products_raw()
            except RuntimeError:
                raised = True
        finally:
            odoo_uid_ctx.reset(token)

    assert raised
