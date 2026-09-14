"""
erp_data/tests/test_bloc_b1_evidence_get_top_selling_products.py

Unit tests for get_top_selling_products_raw()/get_top_selling_products()
(todo/contexte.txt section 727) -- the missing product-ranking ORM tool
found while manually testing "Quels sont les 5 produits les plus vendus
ce mois-ci ?" live via curl: no existing tool aggregated sale.order.line
by product_id, so the ReAct agent silently substituted get_sale_details
(a raw, unranked, unfiltered order list) and presented it with 0.9
confidence as if the question had been answered.

Structurally close to list_out_of_stock_products_raw() (groupby +
Python-side filter/sort, not delegated to Odoo's read_group orderby/limit
kwargs) but on sale.order.line instead of stock.quant, with an added
period filter (reusing build_sale_domain's parse_period helper via a
domain on the related order_id) and a ranking metric switch (quantity vs
revenue). Pure unit tests -- connector.read_group is mocked so these
never touch a live Odoo instance.
"""

import pytest
from unittest.mock import patch

from erp_data.tools.sales import (
    get_top_selling_products_raw,
    get_top_selling_products,
)
from erp_data.odoo_context import odoo_uid_ctx
from core.evidence.evidence import Evidence, EvidenceSourceType


def _rows(*triples):
    """Build a fake read_group result: (name, qty, revenue) triples."""
    return [
        {"product_id": [i + 1, name], "product_uom_qty": qty, "price_subtotal": rev}
        for i, (name, qty, rev) in enumerate(triples)
    ]


def test_top_selling_raw_ranks_by_quantity_by_default():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = _rows(
            ("Chaise", 10.0, 1000.0),
            ("Table", 50.0, 500.0),
            ("Lampe", 5.0, 2000.0),
        )
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_top_selling_products_raw()
        finally:
            odoo_uid_ctx.reset(token)

    # Ranked by quantity desc: Table (50) > Chaise (10) > Lampe (5)
    assert text.index("Table") < text.index("Chaise") < text.index("Lampe")
    assert len(evidence_list) == 3


def test_top_selling_raw_ranks_by_revenue_when_metrique_montant():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = _rows(
            ("Chaise", 10.0, 1000.0),
            ("Table", 50.0, 500.0),
            ("Lampe", 5.0, 2000.0),
        )
        token = odoo_uid_ctx.set(1)
        try:
            text, _evidence_list = get_top_selling_products_raw(metrique="montant")
        finally:
            odoo_uid_ctx.reset(token)

    # Ranked by revenue desc: Lampe (2000) > Chaise (1000) > Table (500)
    assert text.index("Lampe") < text.index("Chaise") < text.index("Table")


def test_top_selling_raw_respects_limite():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = _rows(
            *[(f"P{i}", float(10 - i), 0.0) for i in range(8)]
        )
        token = odoo_uid_ctx.set(1)
        try:
            _text, evidence_list = get_top_selling_products_raw(limite=3)
        finally:
            odoo_uid_ctx.reset(token)

    assert len(evidence_list) == 3


def test_top_selling_raw_default_limite_is_5():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = _rows(
            *[(f"P{i}", float(10 - i), 0.0) for i in range(8)]
        )
        token = odoo_uid_ctx.set(1)
        try:
            _text, evidence_list = get_top_selling_products_raw()
        finally:
            odoo_uid_ctx.reset(token)

    assert len(evidence_list) == 5


def test_top_selling_raw_nonpositive_limite_falls_back_to_5():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = _rows(
            *[(f"P{i}", float(10 - i), 0.0) for i in range(8)]
        )
        token = odoo_uid_ctx.set(1)
        try:
            _text, evidence_list = get_top_selling_products_raw(limite=0)
        finally:
            odoo_uid_ctx.reset(token)

    assert len(evidence_list) == 5


def test_top_selling_raw_no_rows_produces_single_negative_evidence():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = []
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_top_selling_products_raw()
        finally:
            odoo_uid_ctx.reset(token)

    assert "Aucune ligne de vente trouvée" in text
    assert len(evidence_list) == 1
    assert evidence_list[0].value is None


@pytest.mark.parametrize("statut,expected_states", [
    ("toutes", ["draft", "sent", "sale", "done"]),
    ("confirmees", ["sale", "done"]),
    ("brouillon", ["draft", "sent"]),
    ("annulees", ["cancel"]),
])
def test_top_selling_raw_domain_matches_statut_contract(statut, expected_states):
    """Same statut->states contract as every other sales ORM tool
    (todo/contexte.txt section 516), applied here via order_id.state
    (a related-field domain, since the groupby model is sale.order.line
    not sale.order)."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = []
        token = odoo_uid_ctx.set(1)
        try:
            get_top_selling_products_raw(statut=statut)
        finally:
            odoo_uid_ctx.reset(token)

    called_domain = mock_read_group.call_args.kwargs["domain"]
    assert called_domain == [("order_id.state", "in", expected_states)]


def test_top_selling_raw_period_adds_date_domain_on_order_id():
    """A parseable period must add an order_id.date_order range to the
    domain -- verified with an explicit year (deterministic, no need to
    mock today's date), matching parse_period's own contract."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = []
        token = odoo_uid_ctx.set(1)
        try:
            get_top_selling_products_raw(periode="2025")
        finally:
            odoo_uid_ctx.reset(token)

    called_domain = mock_read_group.call_args.kwargs["domain"]
    field_names = [cond[0] for cond in called_domain]
    assert "order_id.date_order" in field_names
    date_conds = [cond for cond in called_domain if cond[0] == "order_id.date_order"]
    assert any(cond[1] == ">=" and cond[2] == "2025-01-01" for cond in date_conds)
    assert any(cond[1] == "<=" and "2025-12-31" in cond[2] for cond in date_conds)


def test_top_selling_raw_unparseable_period_adds_no_date_domain():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = []
        token = odoo_uid_ctx.set(1)
        try:
            get_top_selling_products_raw(periode="toutes")
        finally:
            odoo_uid_ctx.reset(token)

    called_domain = mock_read_group.call_args.kwargs["domain"]
    field_names = [cond[0] for cond in called_domain]
    assert "order_id.date_order" not in field_names


def test_top_selling_raw_source_is_read_group_on_sale_order_line():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = _rows(("Chaise", 1.0, 1.0))
        token = odoo_uid_ctx.set(1)
        try:
            _text, evidence_list = get_top_selling_products_raw()
        finally:
            odoo_uid_ctx.reset(token)

    assert evidence_list[0].source_type == EvidenceSourceType.ORM
    assert evidence_list[0].source == (
        "sale.order.line:read_group(product_uom_qty:sum,price_subtotal:sum, "
        "groupby=product_id)"
    )


def test_top_selling_raw_no_confidence_set():
    """Deterministic ORM read -- never carries a confidence score
    (contract established section 426, reused by every ORM tool)."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = _rows(("Chaise", 1.0, 1.0))
        token = odoo_uid_ctx.set(1)
        try:
            _text, evidence_list = get_top_selling_products_raw()
        finally:
            odoo_uid_ctx.reset(token)

    assert all(e.confidence is None for e in evidence_list)


def test_top_selling_raw_evidence_scope_carries_execution_identity():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = _rows(("Chaise", 1.0, 1.0))
        token = odoo_uid_ctx.set(42)
        try:
            _text, evidence_list = get_top_selling_products_raw()
        finally:
            odoo_uid_ctx.reset(token)

    for e in evidence_list:
        assert e.scope["execution_identity"] == 42
        assert "read_at" in e.scope


def test_top_selling_tool_wrapper_returns_plain_string():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = _rows(("Chaise", 1.0, 1.0))
        token = odoo_uid_ctx.set(1)
        try:
            result = get_top_selling_products.invoke({})
        finally:
            odoo_uid_ctx.reset(token)

    assert isinstance(result, str)
    assert "Chaise" in result


def test_top_selling_tool_wrapper_catches_connector_exceptions():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.side_effect = RuntimeError("boom")
        token = odoo_uid_ctx.set(1)
        try:
            result = get_top_selling_products.invoke({})
        finally:
            odoo_uid_ctx.reset(token)

    assert "Erreur lors du calcul des produits les plus vendus" in result


def test_top_selling_raw_propagates_exceptions_without_fabricating_evidence():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.side_effect = RuntimeError("boom")
        token = odoo_uid_ctx.set(1)
        try:
            raised = False
            try:
                get_top_selling_products_raw()
            except RuntimeError:
                raised = True
        finally:
            odoo_uid_ctx.reset(token)

    assert raised
