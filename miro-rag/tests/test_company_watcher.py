"""
Tests for multi-tenant watcher routing (Step 13 Day 3).

Verifies that file events in company_alpha/ are routed to the company_alpha
Qdrant collection, and events in company_beta/ are routed to company_beta.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ingestion.watcher import _resolve_manager, _default_watch_paths
from vectorstore.chroma_manager import ChromaManager


class TestCompanyWatcher(unittest.TestCase):
    """Test watcher multi-tenant routing."""

    @patch("ingestion.watcher.VECTOR_BACKEND", "qdrant")
    @patch("ingestion.watcher.get_manager_for_collection")
    def test_resolve_manager_alpha(self, mock_get_manager):
        mock_manager = MagicMock()
        mock_get_manager.return_value = mock_manager
        
        chroma_manager = MagicMock(spec=ChromaManager)
        path = Path("fake_data/company_alpha/docs/wiki.txt").resolve()
        manager, is_qdrant = _resolve_manager(path, chroma_manager)

        self.assertTrue(is_qdrant)
        self.assertEqual(manager, mock_manager)
        mock_get_manager.assert_called_once_with("company_alpha")

    @patch("ingestion.watcher.VECTOR_BACKEND", "qdrant")
    @patch("ingestion.watcher.get_manager_for_collection")
    def test_resolve_manager_beta(self, mock_get_manager):
        mock_manager = MagicMock()
        mock_get_manager.return_value = mock_manager
        
        chroma_manager = MagicMock(spec=ChromaManager)
        path = Path("fake_data/company_beta/code/test.py").resolve()
        manager, is_qdrant = _resolve_manager(path, chroma_manager)

        self.assertTrue(is_qdrant)
        self.assertEqual(manager, mock_manager)
        mock_get_manager.assert_called_once_with("company_beta")

    @patch("ingestion.watcher.VECTOR_BACKEND", "qdrant")
    def test_resolve_manager_unmatched(self):
        chroma_manager = MagicMock(spec=ChromaManager)
        path = Path("fake_data/documents/wiki.txt").resolve()
        manager, is_qdrant = _resolve_manager(path, chroma_manager)

        self.assertFalse(is_qdrant)
        self.assertEqual(manager, chroma_manager)

    @patch("ingestion.watcher.VECTOR_BACKEND", "chroma")
    def test_resolve_manager_chroma_backend(self):
        chroma_manager = MagicMock(spec=ChromaManager)
        path = Path("fake_data/company_alpha/docs/wiki.txt").resolve()
        manager, is_qdrant = _resolve_manager(path, chroma_manager)

        self.assertFalse(is_qdrant)
        self.assertEqual(manager, chroma_manager)

    @patch("ingestion.watcher.VECTOR_BACKEND", "qdrant")
    @patch("ingestion.watcher.get_company_docs_dirs")
    def test_default_watch_paths_qdrant(self, mock_get_dirs):
        alpha_docs = Path("fake_data/company_alpha/docs")
        beta_docs = Path("fake_data/company_beta/docs")
        
        mock_get_dirs.return_value = {
            "company_alpha": [alpha_docs],
            "company_beta": [beta_docs],
        }

        paths = _default_watch_paths()

        self.assertEqual(len(paths), 2)
        self.assertIn(alpha_docs, paths)
        self.assertIn(beta_docs, paths)


if __name__ == "__main__":
    unittest.main()
