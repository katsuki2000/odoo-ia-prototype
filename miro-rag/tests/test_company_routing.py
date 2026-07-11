"""
Tests for multi-tenant Qdrant collection routing (Step 13 Day 2).

Verifies that company_id selects the correct Qdrant collection and that
queries never cross company boundaries.
"""

import unittest
from unittest.mock import patch

from qdrant_client import QdrantClient

from vectorstore.company_collections import (
    clear_retriever_cache,
    collection_name_for_company,
    get_company_retriever,
)
from vectorstore.qdrant_manager import QdrantManager
from vectorstore.search import retrieve


class TestCompanyCollectionRouting(unittest.TestCase):
    """Company-scoped retrieval isolation tests."""

    ALPHA_ID = 101
    BETA_ID = 102

    @classmethod
    def setUpClass(cls):
        cls.client = QdrantClient(location=":memory:")

    def setUp(self):
        clear_retriever_cache()
        self.company_map = {
            self.ALPHA_ID: "company_alpha",
            self.BETA_ID: "company_beta",
        }

        self.alpha_manager = QdrantManager(
            client=self.client,
            collection_name="company_alpha",
            embedding_model="all-MiniLM-L6-v2",
        )
        self.beta_manager = QdrantManager(
            client=self.client,
            collection_name="company_beta",
            embedding_model="all-MiniLM-L6-v2",
        )

        self.alpha_manager.add_chunks(
            ["Alpha sales policy for internal staff only."],
            [{"source": "alpha_sales.md", "type": "doc_wiki", "module": "sale"}],
        )
        self.beta_manager.add_chunks(
            ["Beta inventory procedure for warehouse teams."],
            [{"source": "beta_stock.md", "type": "doc_wiki", "module": "stock"}],
        )

    def tearDown(self):
        try:
            self.alpha_manager.delete_collection()
            self.beta_manager.delete_collection()
        except Exception:
            pass
        clear_retriever_cache()

    def test_collection_name_for_company(self):
        with patch("vectorstore.company_collections.COMPANY_COLLECTIONS", self.company_map):
            self.assertEqual(collection_name_for_company(self.ALPHA_ID), "company_alpha")
            self.assertEqual(collection_name_for_company(self.BETA_ID), "company_beta")

    def test_unknown_company_raises(self):
        with patch("vectorstore.company_collections.COMPANY_COLLECTIONS", self.company_map):
            with self.assertRaises(ValueError):
                collection_name_for_company(999)

    def test_alpha_query_returns_alpha_documents_only(self):
        with patch("vectorstore.company_collections.COMPANY_COLLECTIONS", self.company_map):
            manager, bm25 = get_company_retriever(
                self.ALPHA_ID,
                client=self.client,
            )
            results = retrieve(
                "sales policy",
                top_k=5,
                chroma_manager=manager,
                bm25_index=bm25,
                use_reranker=False,
            )

        self.assertGreater(len(results), 0)
        sources = {r["metadata"]["source"] for r in results}
        self.assertIn("alpha_sales.md", sources)
        self.assertNotIn("beta_stock.md", sources)

    def test_beta_query_returns_beta_documents_only(self):
        with patch("vectorstore.company_collections.COMPANY_COLLECTIONS", self.company_map):
            manager, bm25 = get_company_retriever(
                self.BETA_ID,
                client=self.client,
            )
            results = retrieve(
                "inventory procedure",
                top_k=5,
                chroma_manager=manager,
                bm25_index=bm25,
                use_reranker=False,
            )

        self.assertGreater(len(results), 0)
        sources = {r["metadata"]["source"] for r in results}
        self.assertIn("beta_stock.md", sources)
        self.assertNotIn("alpha_sales.md", sources)

    def test_retrievers_use_different_collections(self):
        with patch("vectorstore.company_collections.COMPANY_COLLECTIONS", self.company_map):
            alpha_manager, _ = get_company_retriever(self.ALPHA_ID, client=self.client)
            beta_manager, _ = get_company_retriever(self.BETA_ID, client=self.client)

        self.assertEqual(alpha_manager.collection_name, "company_alpha")
        self.assertEqual(beta_manager.collection_name, "company_beta")
        self.assertNotEqual(alpha_manager, beta_manager)


if __name__ == "__main__":
    unittest.main()
