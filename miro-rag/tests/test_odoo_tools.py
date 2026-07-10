"""
miro-rag/tests/test_odoo_tools.py

Comprehensive tests for Odoo LangChain tools and date_utils.
Validates read-only enforcement, whitelist protection, and accurate date parsing.
"""

import pytest
from tools.odoo_tools import (
    obtenir_total_ventes,
    obtenir_stock_produit,
    obtenir_statut_commande,
    obtenir_total_factures,
    rechercher_client,
    obtenir_tickets_recents,
    lister_produits_en_rupture,
    obtenir_ca_periode,
    connector,
    _get_current_uid
)
from tools.date_utils import parse_period
from tools.odoo_connector import OdooConnectorError

# -----------------------------------------------------------------------------
# Test Utilities (date_utils)
# -----------------------------------------------------------------------------
def test_parse_period_valid():
    """Verify parse_period handles common French expressions correctly."""
    # We test relative expressions dynamically or check they don't crash
    res_ce_mois = parse_period("ce mois")
    assert res_ce_mois is not None
    assert len(res_ce_mois) == 2
    
    res_q1 = parse_period("Q1 2026")
    assert res_q1 == ("2026-01-01", "2026-03-31")
    
    res_year = parse_period("2024")
    assert res_year == ("2024-01-01", "2024-12-31")
    
    res_invalid = parse_period("n'importe quoi")
    assert res_invalid is None

# -----------------------------------------------------------------------------
# Integration Tests for LangChain Tools
# -----------------------------------------------------------------------------
@pytest.mark.integration
class TestOdooTools:
    
    def test_obtenir_total_ventes(self):
        """Test sales aggregation tool."""
        res = obtenir_total_ventes.invoke({'client': 'Rakoto', 'periode': 'cette annee'})
        assert isinstance(res, str)
        # Assuming either a number or a fallback message
        assert "Ar" in res or "Aucune vente" in res

    def test_obtenir_stock_produit(self):
        """Test stock quantity tool."""
        res = obtenir_stock_produit.invoke({'produit': 'Laptop'})
        assert isinstance(res, str)
        assert "stock" in res.lower()

    def test_obtenir_statut_commande(self):
        """Test order status tool."""
        # 'S00001' might not exist in all environments, but it should return a safe string
        res = obtenir_statut_commande.invoke({'reference': 'S00001'})
        assert isinstance(res, str)
        assert "statut" in res or "n'existe pas" in res

    def test_obtenir_total_factures(self):
        """Test invoice aggregation tool."""
        res = obtenir_total_factures.invoke({'client': 'Rakoto', 'statut': 'impayé'})
        assert isinstance(res, str)
        assert "Ar" in res or "Aucune facture" in res

    def test_rechercher_client(self):
        """Test client search tool."""
        res = rechercher_client.invoke({'nom': 'Rakoto'})
        assert isinstance(res, str)
        assert "trouvé" in res or "Aucun client" in res

    def test_obtenir_tickets_recents(self):
        """Test support tickets tool."""
        res = obtenir_tickets_recents.invoke({'client': 'Rakoto', 'limite': 2})
        assert isinstance(res, str)
        assert "ticket" in res.lower()

    def test_lister_produits_en_rupture(self):
        """Test out of stock tool."""
        res = lister_produits_en_rupture.invoke({})
        assert isinstance(res, str)
        assert "produit" in res.lower()

    def test_obtenir_ca_periode(self):
        """Test revenue tool."""
        res = obtenir_ca_periode.invoke({'periode': '2024'})
        assert isinstance(res, str)
        assert "chiffre d'affaires" in res.lower() or "ca" in res.lower()

# -----------------------------------------------------------------------------
# Security & Enforcement Tests
# -----------------------------------------------------------------------------
@pytest.mark.integration
def test_read_only_enforcement():
    """Verify that writing/creating is impossible via our connector methods."""
    uid = _get_current_uid()
    # The connector only exposes search_read, read_group, fields_get.
    # It does not have a write() or create() method.
    assert not hasattr(connector, 'write')
    assert not hasattr(connector, 'create')
    assert not hasattr(connector, 'unlink')

@pytest.mark.integration
def test_whitelist_enforcement():
    """Verify the connector blocks queries to non-whitelisted models."""
    uid = _get_current_uid()
    with pytest.raises(OdooConnectorError) as exc_info:
        connector.search_read(uid, "res.users", [], [])
    assert "not whitelisted" in str(exc_info.value)
