"""
Unit tests for vectorstore/chroma_manager.py

Tests cover:
- Chunk addition with metadata
- Query functionality
- Deletion operations (by source and by ID)
- Collection statistics
- Metadata validation
"""

import tempfile
import unittest
from pathlib import Path

from tests.vector_manager_tests import VectorManagerTestMixin
from vectorstore.chroma_manager import ChromaManager


class TestChromaManager(VectorManagerTestMixin, unittest.TestCase):
    """Test suite for ChromaManager."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp()
        cls.db_path = Path(cls.temp_dir) / "test_chroma"

    def setUp(self):
        self.manager = ChromaManager(
            db_path=self.db_path,
            collection_name="test_collection",
        )

    def tearDown(self):
        try:
            self.manager.delete_collection()
        except Exception:
            pass

    def test_initialization(self):
        self.assertIsNotNone(self.manager.client)
        self.assertIsNotNone(self.manager.collection)
        super().test_initialization()


if __name__ == "__main__":
    unittest.main()
