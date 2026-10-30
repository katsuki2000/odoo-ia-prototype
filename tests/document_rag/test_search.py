"""
Tests for the hybrid search module (vectorstore/search.py).

Covers:
- BM25 tokenization and indexing
- Vector search
- BM25 search
- Reciprocal Rank Fusion (RRF)
- Cross-encoder re-ranking
- Full retrieve() pipeline
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import pytest

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "document_rag"))

from document_rag.vectorstore.search import (
    BM25Index,
    _tokenize,
    hybrid_search,
    reciprocal_rank_fusion,
    retrieve,
    vector_search,
)
from document_rag.vectorstore.chroma_manager import ChromaManager
from document_rag.vectorstore.search_contiguous import fetch_source_chunks


class TestTokenizer(unittest.TestCase):
    """Test the BM25 tokenizer."""

    def test_basic_tokenization(self):
        tokens = _tokenize("Comment créer une facture dans Odoo ?")
        # "comment", "creer", "facture", "odoo" — stops removed
        self.assertIn("comment", tokens)
        self.assertIn("facture", tokens)
        self.assertIn("odoo", tokens)
        # "une" and "dans" are stop words
        self.assertNotIn("une", tokens)
        self.assertNotIn("dans", tokens)

    def test_accented_words_are_not_split(self):
        self.assertEqual(_tokenize("Contrôle des écritures défensif"), ["controle", "ecritures", "defensif"])

    def test_code_tokens_preserved(self):
        tokens = _tokenize("def _compute_total(self): account_move_line")
        self.assertIn("_compute_total", tokens)
        self.assertIn("account_move_line", tokens)
        self.assertIn("def", tokens)

    def test_empty_input(self):
        self.assertEqual(_tokenize(""), [])
        self.assertEqual(_tokenize("   "), [])

    def test_stop_words_filtered(self):
        tokens = _tokenize("le la les un une des du de")
        self.assertEqual(tokens, [])

    def test_short_tokens_filtered(self):
        tokens = _tokenize("a b c test ok")
        # "a", "b", "c" filtered (len <= 1), "ok" kept
        self.assertNotIn("a", tokens)
        self.assertIn("ok", tokens)
        self.assertIn("test", tokens)


class TestRRF(unittest.TestCase):
    """Test Reciprocal Rank Fusion."""

    def _make_result(self, doc_id, text="dummy", score=1.0):
        return {
            "id": doc_id,
            "document": text,
            "metadata": {"source": "test"},
            "score": score,
        }

    def test_basic_fusion(self):
        vec = [self._make_result("a"), self._make_result("b")]
        bm25 = [self._make_result("b"), self._make_result("c")]

        fused = reciprocal_rank_fusion(vec, bm25, relevance_threshold=0.0)

        # "b" appears in both → highest score
        ids = [r["id"] for r in fused]
        self.assertEqual(ids[0], "b")
        self.assertIn("a", ids)
        self.assertIn("c", ids)

    def test_empty_inputs(self):
        fused = reciprocal_rank_fusion([], [], relevance_threshold=0.0)
        self.assertEqual(fused, [])

    def test_single_source(self):
        vec = [self._make_result("x"), self._make_result("y")]
        fused = reciprocal_rank_fusion(vec, [], relevance_threshold=0.0)
        self.assertEqual(len(fused), 2)

    def test_threshold_filtering(self):
        vec = [self._make_result("a")]
        bm25 = [self._make_result("b")]

        # With a high threshold, results with low RRF scores get filtered
        fused_low = reciprocal_rank_fusion(vec, bm25, relevance_threshold=0.0)
        fused_high = reciprocal_rank_fusion(vec, bm25, relevance_threshold=0.99)

        self.assertGreaterEqual(len(fused_low), len(fused_high))

    def test_weights_affect_ranking(self):
        vec = [self._make_result("a"), self._make_result("b")]
        bm25 = [self._make_result("b"), self._make_result("a")]

        # Heavy vector weight → "a" should rank higher (rank 1 in vector)
        fused_vec_heavy = reciprocal_rank_fusion(
            vec, bm25, vector_weight=0.9, bm25_weight=0.1, relevance_threshold=0.0
        )
        # Heavy BM25 weight → "b" should rank higher (rank 1 in BM25)
        fused_bm25_heavy = reciprocal_rank_fusion(
            vec, bm25, vector_weight=0.1, bm25_weight=0.9, relevance_threshold=0.0
        )

        self.assertEqual(fused_vec_heavy[0]["id"], "a")
        self.assertEqual(fused_bm25_heavy[0]["id"], "b")

    def test_rrf_scores_normalized(self):
        vec = [self._make_result("a"), self._make_result("b")]
        bm25 = [self._make_result("c")]

        fused = reciprocal_rank_fusion(vec, bm25, relevance_threshold=0.0)

        # Max score should be 1.0 (normalized)
        self.assertAlmostEqual(fused[0]["rrf_score"], 1.0)
        # All scores in [0, 1]
        for r in fused:
            self.assertGreaterEqual(r["rrf_score"], 0.0)
            self.assertLessEqual(r["rrf_score"], 1.0)


@pytest.mark.embedding_server
class TestBM25Index(unittest.TestCase):
    """Test BM25 index building and searching."""

    def setUp(self):
        """Create a temporary ChromaDB with sample data."""
        self.temp_dir = tempfile.mkdtemp()
        self.chroma = ChromaManager(
            db_path=self.temp_dir,
            collection_name="test_bm25",
        )

        # Add sample documents
        self.sample_texts = [
            "Comment créer une facture dans le module de comptabilité Odoo",
            "La gestion des stocks dans Odoo 17 utilise le module stock",
            "class AccountMove(models.Model): _name = 'account.move'",
            "def _compute_total(self): calcul du montant total de la commande",
            "Les ventes sont gérées par le module sale dans Odoo",
        ]
        self.sample_metadatas = [
            {"source": "doc1.pdf", "type": "doc_pdf", "module": "account"},
            {"source": "doc2.pdf", "type": "doc_pdf", "module": "stock"},
            {"source": "account_move.py", "type": "code_python", "module": "account"},
            {"source": "sale_order.py", "type": "code_python", "module": "sale"},
            {"source": "doc3.pdf", "type": "doc_pdf", "module": "sale"},
        ]

        self.chroma.add_chunks(self.sample_texts, self.sample_metadatas)

    def test_build_from_chroma(self):
        idx = BM25Index()
        count = idx.build_from_chroma(self.chroma)
        self.assertEqual(count, 5)
        self.assertTrue(idx.is_built)
        self.assertEqual(idx.size, 5)

    def test_search_returns_relevant(self):
        idx = BM25Index()
        idx.build_from_chroma(self.chroma)

        results = idx.search("facture comptabilité", top_k=3)
        self.assertTrue(len(results) > 0)
        # First result should be the invoice/accounting doc
        self.assertIn("facture", results[0]["document"].lower())

    def test_search_code(self):
        idx = BM25Index()
        idx.build_from_chroma(self.chroma)

        results = idx.search("AccountMove account.move", top_k=3)
        self.assertTrue(len(results) > 0)
        self.assertIn("AccountMove", results[0]["document"])

    def test_empty_query(self):
        idx = BM25Index()
        idx.build_from_chroma(self.chroma)

        results = idx.search("", top_k=3)
        self.assertEqual(results, [])

    def test_not_built_returns_empty(self):
        idx = BM25Index()
        results = idx.search("test", top_k=3)
        self.assertEqual(results, [])


@pytest.mark.embedding_server
class TestVectorSearch(unittest.TestCase):
    """Test vector search via ChromaDB."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.chroma = ChromaManager(
            db_path=self.temp_dir,
            collection_name="test_vector",
        )

        texts = [
            "Comment créer une facture dans Odoo",
            "Gestion des stocks et inventaire",
            "class SaleOrder(models.Model): _name = 'sale.order'",
        ]
        metadatas = [
            {"source": "doc1.pdf", "type": "doc_pdf", "module": "account"},
            {"source": "doc2.pdf", "type": "doc_pdf", "module": "stock"},
            {"source": "sale.py", "type": "code_python", "module": "sale"},
        ]
        self.chroma.add_chunks(texts, metadatas)

    def test_basic_vector_search(self):
        # Mock au niveau ChromaManager.query() : ce test verifie la logique de
        # filtrage/scoring de vector_search() (Option A, todo/contexte.txt
        # Section 719/720), pas la qualite semantique reelle d'un modele
        # d'embedding (qui varie selon EMBEDDING_BACKEND et n'a pas a etre
        # un pre-requis pour ce test unitaire).
        fake_raw = {
            "results": [
                {
                    "id": "doc1-chunk0",
                    "document": "Comment créer une facture dans Odoo",
                    "distance": 0.1,
                    "similarity": 0.9,
                    "metadata": {"source": "doc1.pdf", "type": "doc_pdf", "module": "account"},
                },
            ],
            "count": 1,
        }
        with patch.object(self.chroma, "query", return_value=fake_raw) as mock_query:
            results = vector_search(self.chroma, "créer facture", top_k=2)
        mock_query.assert_called_once_with(query_text="créer facture", top_k=2, where=None)
        self.assertTrue(len(results) > 0)
        self.assertIn("score", results[0])

    def test_vector_search_with_filter(self):
        results = vector_search(
            self.chroma, "modèle Odoo", top_k=5,
            where={"type": {"$eq": "code_python"}}
        )
        for r in results:
            self.assertEqual(r["metadata"]["type"], "code_python")


@pytest.mark.embedding_server
class TestHybridSearch(unittest.TestCase):
    """Test full hybrid search pipeline."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.chroma = ChromaManager(
            db_path=self.temp_dir,
            collection_name="test_hybrid",
        )

        texts = [
            "Comment créer une facture client dans le module comptabilité Odoo 17",
            "La gestion des stocks utilise les emplacements et les règles de réassort",
            "class AccountMove(models.Model): _name = 'account.move' _inherit = 'mail.thread'",
            "def action_post(self): Valider et publier la facture avec vérification des lignes",
            "Les commandes de vente sont créées depuis le module Sale dans Odoo",
        ]
        metadatas = [
            {"source": "compta.pdf", "type": "doc_pdf", "module": "account"},
            {"source": "stock.pdf", "type": "doc_pdf", "module": "stock"},
            {"source": "account_move.py", "type": "code_python", "module": "account"},
            {"source": "account_move.py", "type": "code_python", "module": "account"},
            {"source": "ventes.pdf", "type": "doc_pdf", "module": "sale"},
        ]
        self.chroma.add_chunks(texts, metadatas)

        self.bm25 = BM25Index()
        self.bm25.build_from_chroma(self.chroma)

    def test_hybrid_returns_results(self):
        results = hybrid_search(
            self.chroma, self.bm25, "facture comptabilité Odoo",
            relevance_threshold=0.0,
        )
        self.assertTrue(len(results) > 0)

    def test_hybrid_combines_both_sources(self):
        # A query that has strong keyword match AND semantic match
        results = hybrid_search(
            self.chroma, self.bm25, "AccountMove account.move facture",
            relevance_threshold=0.0,
        )
        self.assertTrue(len(results) >= 2)

    def test_threshold_filters_results(self):
        results_low = hybrid_search(
            self.chroma, self.bm25, "facture",
            relevance_threshold=0.0,
        )
        results_high = hybrid_search(
            self.chroma, self.bm25, "facture",
            relevance_threshold=0.9,
        )
        self.assertGreaterEqual(len(results_low), len(results_high))


@pytest.mark.embedding_server
class TestRetrievePipeline(unittest.TestCase):
    """Test the full retrieve() pipeline end-to-end."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.chroma = ChromaManager(
            db_path=self.temp_dir,
            collection_name="test_retrieve",
        )

        texts = [
            "Comment créer une facture client dans le module comptabilité Odoo 17",
            "La gestion des stocks utilise les emplacements et les règles de réassort",
            "class AccountMove(models.Model): _name = 'account.move' _inherit = 'mail.thread'",
            "def action_post(self): Valider et publier la facture avec vérification",
            "Les commandes de vente sont créées depuis le module Sale dans Odoo",
            "Le module CRM gère les opportunités et le pipeline commercial",
            "Odoo utilise le framework OWL pour les composants JavaScript frontend",
            "Les droits d'accès sont définis dans ir.model.access.csv",
        ]
        metadatas = [
            {"source": "compta.pdf", "type": "doc_pdf", "module": "account"},
            {"source": "stock.pdf", "type": "doc_pdf", "module": "stock"},
            {"source": "account_move.py", "type": "code_python", "module": "account"},
            {"source": "account_move.py", "type": "code_python", "module": "account"},
            {"source": "ventes.pdf", "type": "doc_pdf", "module": "sale"},
            {"source": "crm.pdf", "type": "doc_pdf", "module": "crm"},
            {"source": "owl.pdf", "type": "doc_wiki", "module": "web"},
            {"source": "security.pdf", "type": "doc_pdf", "module": "base"},
        ]
        self.chroma.add_chunks(texts, metadatas)

    def test_full_pipeline(self):
        results = retrieve(
            "Comment créer une facture ?",
            top_k=3,
            chroma_manager=self.chroma,
        )
        self.assertTrue(len(results) > 0)
        self.assertLessEqual(len(results), 3)

    def test_pipeline_returns_rrf_scores(self):
        results = retrieve(
            "gestion stock",
            top_k=3,
            chroma_manager=self.chroma,
        )
        self.assertTrue(len(results) > 0)
        self.assertIn("rrf_score", results[0])

    def test_pipeline_code_query(self):
        results = retrieve(
            "AccountMove action_post",
            top_k=3,
            chroma_manager=self.chroma,
        )
        self.assertTrue(len(results) > 0)

    def test_pipeline_no_results_for_irrelevant(self):
        results = retrieve(
            "quantum physics black hole",
            top_k=3,
            chroma_manager=self.chroma,
            relevance_threshold=0.8,
        )
        # Should have few or no results for totally irrelevant query
        # (threshold is high)
        self.assertLessEqual(len(results), 3)


def test_vector_search_lets_a_backend_failure_reach_the_caller():
    manager = Mock()
    manager.query.side_effect = ConnectionError("embedding server unreachable")
    with pytest.raises(ConnectionError):
        vector_search(manager, "question")


if __name__ == "__main__":
    unittest.main()


def test_hybrid_search_applies_metadata_filters_to_bm25_candidates():
    manager = Mock()
    manager.query.return_value = {"results": [], "count": 0}
    manager.collection.get.return_value = {"ids": ["allowed"]}
    bm25 = Mock()
    bm25.search.return_value = [
        {"id": "allowed", "document": "matching allowed chunk", "metadata": {"module": "account"}, "score": 2.0},
        {"id": "blocked", "document": "matching blocked chunk", "metadata": {"module": "sale"}, "score": 1.0},
    ]

    results = hybrid_search(
        manager, bm25, "matching", where={"module": {"$eq": "account"}}, relevance_threshold=0.0
    )

    assert [item["id"] for item in results] == ["allowed"]
    manager.collection.get.assert_called_once_with(where={"module": {"$eq": "account"}}, include=[])


def test_bm25_index_build_propagates_collection_read_failures():
    manager = Mock()
    manager.collection.get.side_effect = RuntimeError("collection unavailable")

    with pytest.raises(RuntimeError, match="collection unavailable"):
        BM25Index().build_from_chroma(manager)


def test_fetch_source_chunks_reads_all_configured_collections():
    first = Mock()
    first.collection.get.return_value = {
        "ids": ["chunk-0"], "documents": ["first"],
        "metadatas": [{"source": "manual.pdf", "chunk_index": 0}],
    }
    second = Mock()
    second.collection.get.return_value = {
        "ids": ["chunk-1"], "documents": ["second"],
        "metadatas": [{"source": "manual.pdf", "chunk_index": 1}],
    }

    chunks = fetch_source_chunks([first, second], "manual.pdf")

    assert [chunks[index]["id"] for index in sorted(chunks)] == ["chunk-0", "chunk-1"]


def test_fetch_source_chunks_uses_the_collection_containing_the_seed_chunk():
    first = Mock()
    first.collection.get.side_effect = [
        {"ids": ["chunk-0"], "metadatas": [{"source": "manual.pdf", "chunk_index": 0}]},
        {"ids": ["chunk-0"], "documents": ["first"],
         "metadatas": [{"source": "manual.pdf", "chunk_index": 0}]},
    ]
    second = Mock()
    second.collection.get.return_value = {
        "ids": ["chunk-1"], "metadatas": [{"source": "manual.pdf", "chunk_index": 1}],
    }

    chunks = fetch_source_chunks([first, second], "manual.pdf", chunk_id="chunk-0")

    assert list(chunks) == [0]
    second.collection.get.assert_called_once_with(ids=["chunk-0"], include=["metadatas"])
