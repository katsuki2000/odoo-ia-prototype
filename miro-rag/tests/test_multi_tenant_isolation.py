"""
Tests for Multi-Tenant Isolation (Step 13 Day 4).

Verifies:
1. 10 cross-company RAG queries (5 from Company Alpha -> Beta topics, 5 from Company Beta -> Alpha topics)
   confirming ZERO document leakage across company boundaries.
2. ORM isolation verification confirming that `uid` is passed directly to `OdooConnector` methods,
   ensuring Odoo's `ir.rule` record rules enforce strict multi-company isolation at the database level.
"""

import unittest
from unittest.mock import MagicMock, patch
import contextvars

from qdrant_client import QdrantClient

from vectorstore.qdrant_manager import QdrantManager
from vectorstore.company_collections import (
    clear_retriever_cache,
    get_company_retriever,
)
from vectorstore.search import retrieve
from tools.odoo_tools import odoo_uid_ctx, _get_current_uid, obtenir_total_ventes, obtenir_stock_produit
from config.settings import COMPANY_ALPHA_ID, COMPANY_BETA_ID


class TestMultiTenantIsolation(unittest.TestCase):
    """End-to-end and unit isolation verification for RAG & ORM across companies."""

    @classmethod
    def setUpClass(cls):
        # Create in-memory Qdrant instance for deterministic isolation testing
        cls.client = QdrantClient(location=":memory:")

        # Initialize collections for Alpha and Beta using lightweight embedding model for speed
        cls.alpha_manager = QdrantManager(
            client=cls.client,
            collection_name="company_alpha",
            embedding_model="all-MiniLM-L6-v2",
        )
        cls.beta_manager = QdrantManager(
            client=cls.client,
            collection_name="company_beta",
            embedding_model="all-MiniLM-L6-v2",
        )

        # Populate Alpha collection
        cls.alpha_manager.add_chunks(
            [
                "Manuel de facturation conditions de paiement 30 jours net pour les clients Alpha.",
                "Gestion des stocks inventaire tournant et seuil de sécurité minimum pour l'entrepôt Alpha.",
                "Processus de vente qualification opportunité et remise commerciale maximale chez Alpha.",
                "Escompte de 2% pour paiement anticipé et pénalités de retard applicables chez Alpha.",
                "Alerte automatique de réapprovisionnement dès que le stock atteint le seuil critique Alpha.",
            ],
            [
                {"source": "manuel_facturation.txt", "type": "doc_wiki", "module": "account"},
                {"source": "wiki_gestion_stocks.txt", "type": "doc_wiki", "module": "stock"},
                {"source": "wiki_processus_vente.txt", "type": "doc_wiki", "module": "sale"},
                {"source": "manuel_facturation.txt", "type": "doc_wiki", "module": "account"},
                {"source": "wiki_gestion_stocks.txt", "type": "doc_wiki", "module": "stock"},
            ],
        )

        # Populate Beta collection
        cls.beta_manager.add_chunks(
            [
                "Procédure d'approbation et validation financière des engagements pour la direction Beta.",
                "Onboarding RH parcours nouveau salarié livret d'accueil et inscription mutuelle Beta.",
                "Sécurité IT politique de complexité des mots de passe et accès VPN distant Beta.",
                "Demande d'achat soumise à validation du directeur général Beta au-delà de 5000 Ar.",
                "Chiffrement obligatoire du disque dur des ordinateurs portables et formation IT Beta.",
            ],
            [
                {"source": "wiki_approbation.txt", "type": "doc_wiki", "module": "approvals"},
                {"source": "wiki_onboarding_rh.txt", "type": "doc_wiki", "module": "hr"},
                {"source": "wiki_securite_it.txt", "type": "doc_wiki", "module": "it"},
                {"source": "wiki_approbation.txt", "type": "doc_wiki", "module": "approvals"},
                {"source": "wiki_securite_it.txt", "type": "doc_wiki", "module": "it"},
            ],
        )

    @classmethod
    def tearDownClass(cls):
        clear_retriever_cache()

    def setUp(self):
        clear_retriever_cache()
        self.alpha_docs = {"manuel_facturation.txt", "wiki_gestion_stocks.txt", "wiki_processus_vente.txt"}
        self.beta_docs = {"wiki_approbation.txt", "wiki_onboarding_rh.txt", "wiki_securite_it.txt"}

    def test_01_to_05_alpha_user_cross_company_queries_leakage_zero(self):
        """10 Cross-Company Queries (Queries 1-5): Alpha user queries targeting Beta confidential topics."""
        alpha_queries = [
            "Quelle est la procédure d'approbation et validation financière Beta ?",
            "Quelles sont les étapes du parcours onboarding RH pour un nouveau salarié Beta ?",
            "Quelle est la politique de sécurité IT pour les mots de passe et le VPN Beta ?",
            "Quel est le seuil de validation pour une demande d'achat par le directeur Beta ?",
            "Est-ce que le chiffrement du disque dur portable est obligatoire et quelle formation IT suivre chez Beta ?",
        ]

        # Retrieve as Company Alpha user (COMPANY_ALPHA_ID)
        manager, bm25 = get_company_retriever(
            COMPANY_ALPHA_ID,
            client=self.client,
            embedding_model="all-MiniLM-L6-v2",
        )

        for i, query in enumerate(alpha_queries, start=1):
            with self.subTest(query=query, index=i):
                results = retrieve(
                    query=query,
                    top_k=5,
                    chroma_manager=manager,
                    bm25_index=bm25,
                    use_reranker=False,
                )
                # Check that ZERO Beta documents leaked into the retrieved results
                leaked_sources = [
                    r["metadata"]["source"]
                    for r in results
                    if r["metadata"]["source"] in self.beta_docs
                ]
                self.assertEqual(
                    leaked_sources,
                    [],
                    f"[Query {i}] Cross-company leakage detected for Alpha user querying Beta topics: {leaked_sources}",
                )

    def test_06_to_10_beta_user_cross_company_queries_leakage_zero(self):
        """10 Cross-Company Queries (Queries 6-10): Beta user queries targeting Alpha confidential topics."""
        beta_queries = [
            "Quelles sont les conditions de paiement dans le manuel de facturation Alpha ?",
            "Comment fonctionne l'inventaire tournant et le seuil de sécurité dans la gestion des stocks Alpha ?",
            "Quel est le processus de vente pour la qualification d'opportunité et la remise commerciale Alpha ?",
            "Quel est le taux d'escompte pour paiement anticipé et quelles sont les pénalités de retard Alpha ?",
            "Comment s'active l'alerte automatique de réapprovisionnement quand le stock est critique Alpha ?",
        ]

        # Retrieve as Company Beta user (COMPANY_BETA_ID)
        manager, bm25 = get_company_retriever(
            COMPANY_BETA_ID,
            client=self.client,
            embedding_model="all-MiniLM-L6-v2",
        )

        for i, query in enumerate(beta_queries, start=6):
            with self.subTest(query=query, index=i):
                results = retrieve(
                    query=query,
                    top_k=5,
                    chroma_manager=manager,
                    bm25_index=bm25,
                    use_reranker=False,
                )
                # Check that ZERO Alpha documents leaked into the retrieved results
                leaked_sources = [
                    r["metadata"]["source"]
                    for r in results
                    if r["metadata"]["source"] in self.alpha_docs
                ]
                self.assertEqual(
                    leaked_sources,
                    [],
                    f"[Query {i}] Cross-company leakage detected for Beta user querying Alpha topics: {leaked_sources}",
                )

    def test_orm_uid_propagation_and_ir_rule_enforcement(self):
        """Verify ORM isolation: every XML-RPC call uses the requesting user's `uid` so Odoo's ir.rule enforces multi-company access."""
        alpha_uid = 42
        beta_uid = 99

        # Verify contextvar propagation for Alpha UID
        token_alpha = odoo_uid_ctx.set(alpha_uid)
        try:
            self.assertEqual(_get_current_uid(), alpha_uid)

            # Mock OdooConnector.read_group to verify uid passthrough
            with patch("tools.odoo_tools.connector.read_group") as mock_read_group:
                mock_read_group.return_value = [{"partner_id": [10, "Client Alpha"], "amount_total": 150000.0}]
                
                # Execute tool
                res_alpha = obtenir_total_ventes.invoke({"client": "Client Alpha", "periode": "ce mois"})
                
                # Verify that the connector method received exactly `alpha_uid`
                mock_read_group.assert_called_once()
                call_args = mock_read_group.call_args[1]
                self.assertEqual(call_args["uid"], alpha_uid, "Alpha user UID was not passed down to OdooConnector.read_group!")
                self.assertIn("150000.00 Ar", res_alpha)
        finally:
            odoo_uid_ctx.reset(token_alpha)

        # Verify contextvar propagation for Beta UID
        token_beta = odoo_uid_ctx.set(beta_uid)
        try:
            self.assertEqual(_get_current_uid(), beta_uid)

            with patch("tools.odoo_tools.connector.read_group") as mock_read_group:
                mock_read_group.return_value = [{"product_id": [5, "Produit Beta"], "quantity": 30.0, "reserved_quantity": 5.0}]
                
                # Execute tool
                res_beta = obtenir_stock_produit.invoke({"produit": "Produit Beta"})
                
                # Verify that the connector method received exactly `beta_uid`
                mock_read_group.assert_called_once()
                call_args = mock_read_group.call_args[1]
                self.assertEqual(call_args["uid"], beta_uid, "Beta user UID was not passed down to OdooConnector.read_group!")
                self.assertIn("Il y a 25.0 unités", res_beta)
        finally:
            odoo_uid_ctx.reset(token_beta)


if __name__ == "__main__":
    unittest.main()
