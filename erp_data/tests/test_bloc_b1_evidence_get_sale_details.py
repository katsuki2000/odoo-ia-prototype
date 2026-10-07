"""
erp_data/tests/test_bloc_b1_evidence_get_sale_details.py

B1 replication -- dernier outil ORM du volet B1 (todo/contexte.txt
section 481+). Valide get_sale_details_raw(), le plus structurellement
complexe des 9 tools ORM : deux lectures ORM distinctes par commande
affichee (sale.order + sale.order.line), un fallback intra-modele
(domaine statut-filtre -> domaine elargi state!=cancel), et un total
agrege deliberement sans Evidence dediee (arithmetique sur des faits
deja couverts). Pure unit tests -- connector.search_read est mocke,
aucun acces a une instance Odoo reelle.
"""

from unittest.mock import patch

from erp_data.tools.sales import (
    get_sale_details_raw,
    get_sale_details,
)
from erp_data.odoo_context import odoo_uid_ctx
from core.evidence.evidence import Evidence, EvidenceSourceType


def test_single_order_with_products_two_evidence():
    """Une commande avec produits resolus -> 2 Evidence : une pour les
    faits sale.order, une pour les produits sale.order.line -- sources
    distinctes, jamais un dict fusionne."""
    with patch("erp_data._odoo_helpers.connector.search_read") as mock_sr:
        mock_sr.side_effect = [
            [{"name": "S001", "partner_id": [1, "Rakoto"], "date_order": "2026-01-01",
              "amount_total": 500.0, "state": "sale", "order_line": [10, 11]}],
            [{"product_id": [100, "Chaise"]}, {"product_id": [101, "Table"]}],
        ]
        token = odoo_uid_ctx.set(7)
        try:
            text, evidence_list = get_sale_details_raw("Rakoto", "confirmé", 0)
        finally:
            odoo_uid_ctx.reset(token)

    assert "500.00" in text
    assert "Chaise, Table" in text
    assert len(evidence_list) == 2

    order_ev, prod_ev = evidence_list
    assert isinstance(order_ev, Evidence) and isinstance(prod_ev, Evidence)
    assert order_ev.source_type == EvidenceSourceType.ORM
    assert order_ev.source == "sale.order:search_read(name,state,partner_id,amount_total,currency_id)[domaine=statut]"
    assert order_ev.value == {
        "state": "sale", "partner": "Rakoto", "amount": 500.0,
        "currency": "unspecified",
    }
    assert order_ev.claim == "Order details for name=S001"

    assert prod_ev.source == "sale.order.line:search_read(product_id)"
    assert prod_ev.value == ["Chaise", "Table"]
    assert prod_ev.claim == "Products for order name=S001"


def test_order_state_value_is_raw_not_french_label():
    """Le `value` porte l'etat brut Odoo (ex. 'sale'), pas le libelle
    francais affiche dans le texte -- meme discipline que
    get_order_status_raw : une traduction n'est pas un second fait."""
    with patch("erp_data._odoo_helpers.connector.search_read") as mock_sr:
        mock_sr.side_effect = [
            [{"name": "S001", "partner_id": [1, "Rakoto"], "date_order": "2026-01-01",
              "amount_total": 10.0, "state": "sale", "order_line": []}],
        ]
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_sale_details_raw("Rakoto", "confirmé", 0)
        finally:
            odoo_uid_ctx.reset(token)

    assert "Vente confirmée" in text
    assert evidence_list[0].value["state"] == "sale"


def test_multiple_orders_total_sum_has_no_dedicated_evidence():
    """Le total agrege est une arithmetique sur des faits deja couverts
    par les Evidence par-commande -- aucune Evidence dediee pour le total
    lui-meme, meme principe que `available` dans get_product_stock_raw."""
    with patch("erp_data._odoo_helpers.connector.search_read") as mock_sr:
        mock_sr.side_effect = [
            [
                {"name": "S001", "partner_id": [1, "Rakoto"], "date_order": "2026-01-01",
                 "amount_total": 100.0, "state": "sale", "order_line": []},
                {"name": "S002", "partner_id": [1, "Rakoto"], "date_order": "2026-01-02",
                 "amount_total": 250.0, "state": "draft", "order_line": []},
            ],
        ]
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_sale_details_raw("Rakoto", "toutes", 0)
        finally:
            odoo_uid_ctx.reset(token)

    assert "350.00" in text
    # 2 commandes * 2 Evidence (order + produits) = 4, jamais 5 (pas de total)
    assert len(evidence_list) == 4
    assert not any("350" in str(e.value) for e in evidence_list)
    assert not any("total" in e.claim.lower() for e in evidence_list)


def test_no_order_lines_at_all_positive_evidence_sourced_from_sale_order():
    """order_line vide -> aucune 2e requete tentee -- l'Evidence produits
    reste positive (value=[]) mais sa source doit refleter que le fait
    est connu depuis la lecture sale.order elle-meme, pas une lecture
    sale.order.line qui n'a jamais eu lieu."""
    with patch("erp_data._odoo_helpers.connector.search_read") as mock_sr:
        mock_sr.side_effect = [
            [{"name": "S002", "partner_id": [1, "Rakoto"], "date_order": "2026-01-01",
              "amount_total": 0.0, "state": "draft", "order_line": []}],
        ]
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_sale_details_raw("Rakoto", "brouillon", 0)
        finally:
            odoo_uid_ctx.reset(token)

    assert mock_sr.call_count == 1
    assert "Aucun produit" in text
    prod_ev = evidence_list[1]
    assert prod_ev.value == []
    assert prod_ev.source == "sale.order:search_read(order_line)"


def test_lines_fetched_but_no_product_resolved_sourced_from_sale_order_line():
    """order_line non-vide -> une vraie 2e requete a lieu, meme si elle
    ne resout aucun product_id -- l'Evidence reste positive (value=[])
    mais avec la source sale.order.line, puisque la requete a reellement
    eu lieu, contrairement au cas precedent."""
    with patch("erp_data._odoo_helpers.connector.search_read") as mock_sr:
        mock_sr.side_effect = [
            [{"name": "S003", "partner_id": [1, "Rakoto"], "date_order": "2026-01-01",
              "amount_total": 10.0, "state": "draft", "order_line": [20]}],
            [{"product_id": False}],
        ]
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_sale_details_raw("Rakoto", "brouillon", 0)
        finally:
            odoo_uid_ctx.reset(token)

    assert mock_sr.call_count == 2
    assert "Aucun produit" in text
    prod_ev = evidence_list[1]
    assert prod_ev.value == []
    assert prod_ev.source == "sale.order.line:search_read(product_id)"


def test_fallback_success_sources_from_broader_domain():
    """Domaine primaire (filtre statut) vide, fallback (state!=cancel)
    trouve des records -- la source doit suivre le domaine reellement
    responsable (le fallback), jamais le domaine primaire."""
    with patch("erp_data._odoo_helpers.connector.search_read") as mock_sr:
        mock_sr.side_effect = [
            [],
            [{"name": "S010", "partner_id": [1, "Randria"], "date_order": "2026-01-01",
              "amount_total": 77.0, "state": "draft", "order_line": []}],
        ]
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_sale_details_raw("Randria", "confirmé", 0)
        finally:
            odoo_uid_ctx.reset(token)

    assert "77.00" in text
    order_ev = evidence_list[0]
    assert "repli" in order_ev.source
    assert "domaine=statut" not in order_ev.source


def test_both_domains_empty_negative_evidence_has_composite_source():
    """Quand statut != 'toutes' et que le domaine primaire ET le fallback
    sont reellement vides, la source negative doit nommer les deux
    domaines tentes -- meme discipline que get_total_invoices_raw."""
    with patch("erp_data._odoo_helpers.connector.search_read") as mock_sr:
        mock_sr.side_effect = [[], []]
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_sale_details_raw("Randria", "confirmé", 0)
        finally:
            odoo_uid_ctx.reset(token)

    assert "Randria" in text
    assert len(evidence_list) == 1
    e = evidence_list[0]
    assert e.value is None
    assert "[domaine=statut]" in e.source and "repli" in e.source
    assert "[empty]" in e.source
    assert e.claim == "No sale.order matches client=Randria, statut=confirmé"


def test_statut_toutes_empty_no_fallback_attempted_single_domain_source():
    """statut == 'toutes' -> le domaine 'toutes' est deja le plus large,
    aucun fallback n'est tente -- une seule requete search_read, source
    a un seul domaine sur le cas negatif."""
    with patch("erp_data._odoo_helpers.connector.search_read") as mock_sr:
        mock_sr.side_effect = [[]]
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_sale_details_raw("Randria", "toutes", 0)
        finally:
            odoo_uid_ctx.reset(token)

    assert mock_sr.call_count == 1
    e = evidence_list[0]
    assert "repli" not in e.source
    assert "[domaine=statut] [empty]" in e.source


def test_date_order_excluded_from_every_evidence():
    """date_order est fetche mais jamais affirme dans `text` -- exclu de
    toute Evidence (value) et de tout `source`, meme discipline que
    date_deadline/amount_total dans les tools precedents."""
    with patch("erp_data._odoo_helpers.connector.search_read") as mock_sr:
        mock_sr.side_effect = [
            [{"name": "S001", "partner_id": [1, "Rakoto"], "date_order": "2026-05-05",
              "amount_total": 10.0, "state": "sale", "order_line": []}],
        ]
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_sale_details_raw("Rakoto", "confirmé", 0)
        finally:
            odoo_uid_ctx.reset(token)

    assert "2026-05-05" not in text
    for e in evidence_list:
        assert "date_order" not in e.source
        if isinstance(e.value, dict):
            assert "date_order" not in e.value


def test_no_confidence_ever_set():
    with patch("erp_data._odoo_helpers.connector.search_read") as mock_sr:
        mock_sr.side_effect = [
            [{"name": "S001", "partner_id": [1, "X"], "date_order": "2026-01-01",
              "amount_total": 1.0, "state": "sale", "order_line": []}],
        ]
        token = odoo_uid_ctx.set(1)
        try:
            _text, evidence_list = get_sale_details_raw("X", "confirmé", 0)
        finally:
            odoo_uid_ctx.reset(token)

    assert all(e.confidence is None for e in evidence_list)


def test_evidence_scope_carries_execution_identity_not_company_id():
    with patch("erp_data._odoo_helpers.connector.search_read") as mock_sr:
        mock_sr.side_effect = [
            [{"name": "S001", "partner_id": [1, "X"], "date_order": "2026-01-01",
              "amount_total": 1.0, "state": "sale", "order_line": []}],
        ]
        token = odoo_uid_ctx.set(42)
        try:
            _text, evidence_list = get_sale_details_raw("X", "confirmé", 0)
        finally:
            odoo_uid_ctx.reset(token)

    for e in evidence_list:
        assert e.scope["execution_identity"] == 42
        assert "read_at" in e.scope
        assert "company_id" not in e.scope


def test_tool_wrapper_unchanged_return_contract():
    with patch("erp_data._odoo_helpers.connector.search_read") as mock_sr:
        mock_sr.side_effect = [
            [{"name": "S001", "partner_id": [1, "X"], "date_order": "2026-01-01",
              "amount_total": 1.0, "state": "sale", "order_line": []}],
        ]
        token = odoo_uid_ctx.set(1)
        try:
            result = get_sale_details.invoke({"client": "X", "statut": "toutes", "limite": 0})
        finally:
            odoo_uid_ctx.reset(token)

    assert isinstance(result, str)


def test_tool_wrapper_still_catches_connector_exceptions():
    with patch("erp_data._odoo_helpers.connector.search_read") as mock_sr:
        mock_sr.side_effect = RuntimeError("boom")
        token = odoo_uid_ctx.set(1)
        try:
            result = get_sale_details.invoke({"client": "X", "statut": "toutes", "limite": 0})
        finally:
            odoo_uid_ctx.reset(token)

    assert "Erreur lors de la récupération des détails" in result


def test_raw_propagates_exceptions_without_fabricating_evidence():
    with patch("erp_data._odoo_helpers.connector.search_read") as mock_sr:
        mock_sr.side_effect = RuntimeError("boom")
        token = odoo_uid_ctx.set(1)
        try:
            raised = False
            try:
                get_sale_details_raw("X", "toutes", 0)
            except RuntimeError:
                raised = True
        finally:
            odoo_uid_ctx.reset(token)

    assert raised
