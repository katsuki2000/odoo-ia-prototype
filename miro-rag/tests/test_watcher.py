"""
Tests for Step 5b Day 1 ingestion watcher event handling.
"""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from ingestion.watcher import DebouncedIngestionHandler


class _Event:
    def __init__(self, src_path: str, is_directory: bool = False, dest_path: str = ""):
        self.src_path = src_path
        self.dest_path = dest_path
        self.is_directory = is_directory


class TestDebouncedIngestionHandler(unittest.TestCase):
    """Validate watcher create/modify/delete behavior without starting watchdog."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.manager = MagicMock()
        self.handler = DebouncedIngestionHandler(
            docs_manager=self.manager,
            code_manager=self.manager,
            debounce_seconds=0,
            chunk_size=120,
            chunk_overlap=10,
        )

    def tearDown(self):
        self.handler.stop()
        self.temp_dir.cleanup()

    def test_created_file_triggers_incremental_reindex(self):
        target = self.root / "new_doc.txt"
        target.write_text("New document", encoding="utf-8")

        with patch("ingestion.watcher.reindex_if_changed") as reindex:
            reindex.return_value = {"added_files": [str(target.resolve())], "chunks_added": 1}
            self.handler.on_created(_Event(str(target)))

        reindex.assert_called_once()
        args, kwargs = reindex.call_args
        self.assertEqual(args[0], [target.resolve()])
        self.assertEqual(kwargs.get("docs_manager"), self.manager)
        self.assertEqual(kwargs.get("code_manager"), self.manager)
        self.assertEqual(self.handler.last_event_type, "upsert")
        self.assertEqual(self.handler.last_result.get("chunks_added"), 1)

    def test_modified_file_uses_debounce_key_and_reindexes_once(self):
        target = self.root / "changed_doc.txt"
        target.write_text("Changed document", encoding="utf-8")
        self.handler.debounce_seconds = 0.01

        with patch("ingestion.watcher.Timer") as timer_cls:
            first_timer = MagicMock()
            second_timer = MagicMock()
            timer_cls.side_effect = [first_timer, second_timer]

            self.handler.on_modified(_Event(str(target)))
            self.handler.on_modified(_Event(str(target)))

        first_timer.cancel.assert_called_once()
        second_timer.start.assert_called_once()

    def test_deleted_file_deletes_chunks_by_source(self):
        target = self.root / "removed_doc.txt"
        self.manager.delete_by_source.return_value = 3

        self.handler.on_deleted(_Event(str(target)))

        self.manager.delete_by_source.assert_called_once_with(str(target.resolve()))
        self.assertEqual(self.handler.last_event_type, "delete")
        self.assertEqual(self.handler.last_result.get("chunks_deleted"), 3)

    def test_unsupported_file_is_ignored(self):
        target = self.root / "ignored.tmp"

        with patch("ingestion.watcher.reindex_if_changed") as reindex:
            self.handler.on_created(_Event(str(target)))

        reindex.assert_not_called()
        self.manager.delete_by_source.assert_not_called()


if __name__ == "__main__":
    unittest.main()
