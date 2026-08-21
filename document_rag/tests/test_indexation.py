"""
Tests for Step 5 incremental reindexing.
"""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

from document_rag.ingestion.incremental import reindex_if_changed
from document_rag.vectorstore.chroma_manager import ChromaManager


class TestIncrementalIndexation(unittest.TestCase):
    """Validate modify, delete, and add incremental indexing scenarios."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp_dir.name)
        self.docs_dir = self.root / "docs"
        self.db_path = self.root / "chroma"
        self.docs_dir.mkdir()
        self.manager = ChromaManager(
            db_path=self.db_path,
            collection_name="test_incremental",
        )

    def tearDown(self):
        try:
            self.manager.delete_collection()
        except Exception:
            pass
        try:
            del self.manager
        except Exception:
            pass
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_modify_document_reindexes_only_changed_source(self):
        first_file = self.docs_dir / "first.txt"
        second_file = self.docs_dir / "second.txt"
        third_file = self.docs_dir / "third.txt"
        first_file.write_text("FIRST DOCUMENT\n\nOriginal content.", encoding="utf-8")
        second_file.write_text("SECOND DOCUMENT\n\nStable content.", encoding="utf-8")
        third_file.write_text("THIRD DOCUMENT\n\nOriginal content.", encoding="utf-8")

        initial = reindex_if_changed([self.docs_dir], self.manager, chunk_size=120, chunk_overlap=10)
        self.assertEqual(len(initial.get("added_files", [])), 3)

        wrapped_add_chunks = MagicMock(wraps=self.manager.add_chunks)
        self.manager.add_chunks = wrapped_add_chunks

        first_file.write_text("FIRST DOCUMENT\n\nModified content.", encoding="utf-8")
        third_file.write_text("THIRD DOCUMENT\n\nModified content.", encoding="utf-8")
        with self.assertLogs("ingestion.incremental", level="INFO") as logs:
            changed = reindex_if_changed([self.docs_dir], self.manager, chunk_size=120, chunk_overlap=10)

        self.assertIn(str(first_file.resolve()), changed.get("updated_files", []))
        self.assertIn(str(third_file.resolve()), changed.get("updated_files", []))
        self.assertIn(str(second_file.resolve()), changed.get("skipped_files", []))
        self.assertEqual(changed.get("added_files"), [])
        self.assertEqual(changed.get("deleted_files"), [])
        self.assertEqual(changed.get("chunks_added"), 2)
        self.assertEqual(wrapped_add_chunks.call_count, 2)
        self.assertIn("Skipping unchanged source", "\n".join(logs.output))

    def test_deleted_document_removes_chunks(self):
        deleted_file = self.docs_dir / "delete_me.txt"
        kept_file = self.docs_dir / "keep_me.txt"
        deleted_file.write_text("Delete this content.", encoding="utf-8")
        kept_file.write_text("Keep this content.", encoding="utf-8")

        reindex_if_changed([self.docs_dir], self.manager, chunk_size=120, chunk_overlap=10)
        deleted_file.unlink()
        wrapped_add_chunks = MagicMock(wraps=self.manager.add_chunks)
        self.manager.add_chunks = wrapped_add_chunks

        with self.assertLogs("ingestion.incremental", level="INFO") as logs:
            result = reindex_if_changed([self.docs_dir], self.manager, chunk_size=120, chunk_overlap=10)

        self.assertIn(str(deleted_file.resolve()), result.get("deleted_files", []))
        self.assertIn(str(kept_file.resolve()), result.get("skipped_files", []))
        self.assertEqual(result.get("added_files"), [])
        self.assertEqual(result.get("updated_files"), [])
        self.assertEqual(result.get("chunks_added"), 0)
        self.assertEqual(wrapped_add_chunks.call_count, 0)
        self.assertEqual(self.manager.delete_by_source(str(deleted_file.resolve())), 0)
        self.assertGreaterEqual(self.manager.get_stats().get("total_chunks", 0), 1)
        self.assertIn("Deleted removed source", "\n".join(logs.output))

    def test_added_document_indexes_only_new_source(self):
        existing_file = self.docs_dir / "existing.txt"
        new_file = self.docs_dir / "new.txt"
        existing_file.write_text("Existing content.", encoding="utf-8")

        reindex_if_changed([self.docs_dir], self.manager, chunk_size=120, chunk_overlap=10)
        new_file.write_text("New content.", encoding="utf-8")
        wrapped_add_chunks = MagicMock(wraps=self.manager.add_chunks)
        self.manager.add_chunks = wrapped_add_chunks

        with self.assertLogs("ingestion.incremental", level="INFO") as logs:
            result = reindex_if_changed([self.docs_dir], self.manager, chunk_size=120, chunk_overlap=10)

        self.assertIn(str(new_file.resolve()), result.get("added_files", []))
        self.assertIn(str(existing_file.resolve()), result.get("skipped_files", []))
        self.assertEqual(result.get("updated_files"), [])
        self.assertEqual(result.get("deleted_files"), [])
        self.assertEqual(result.get("chunks_added"), 1)
        self.assertEqual(wrapped_add_chunks.call_count, 1)
        self.assertIn("Added new source", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
