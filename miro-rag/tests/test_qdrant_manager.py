"""
Unit tests for vectorstore/qdrant_manager.py.

Reuses the same behavioral contract as test_chroma_manager.py.
"""

import unittest

from tests.vector_manager_tests import VectorManagerTestMixin
from vectorstore.qdrant_manager import QdrantManager


class TestQdrantManager(VectorManagerTestMixin, unittest.TestCase):
    """Test suite for QdrantManager."""

    def setUp(self):
        self.manager = QdrantManager(
            url=":memory:",
            collection_name="test_collection",
            embedding_model="all-MiniLM-L6-v2",
        )

    def tearDown(self):
        try:
            self.manager.delete_collection()
        except Exception:
            pass


if __name__ == "__main__":
    unittest.main()
