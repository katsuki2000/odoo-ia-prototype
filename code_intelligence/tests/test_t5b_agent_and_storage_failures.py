import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import chromadb
import pytest

from code_intelligence.agent.tool_helpers import _is_custom_module_filepath
from core.llm.llm_retry import try_recover_tool_use_failed
from document_rag.ingestion.incremental import _is_under_roots
from document_rag.vectorstore.chroma_helpers import get_or_create_collection, reset_collection


def _warnings(caplog):
    return [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]


def test_custom_module_check_logs_an_unresolvable_path_and_falls_back(caplog):
    with patch.object(Path, "resolve", side_effect=OSError("loop")):
        assert isinstance(_is_custom_module_filepath("/tmp/custom_x/models/a.py"), bool)
    assert any("Cannot resolve path" in message for message in _warnings(caplog))


def test_malformed_tool_call_arguments_are_not_recovered(caplog):
    caplog.set_level(logging.DEBUG)
    message = "tool_use_failed: <function=lookup>{not json}</function>"
    with patch("core.llm.llm_retry._TOOL_USE_FAILED_RE") as outer, patch("core.llm.llm_retry._FAILED_GEN_CALL_RE") as inner:
        outer.search.return_value = MagicMock(group=lambda index: "x")
        inner.search.return_value = MagicMock(group=lambda index: "lookup" if index == 1 else "{not json}")
        assert try_recover_tool_use_failed(Exception(message)) is None
    assert any("not valid JSON" in record.getMessage() for record in caplog.records)


def test_unresolvable_scan_candidate_is_logged_and_skipped(tmp_path, caplog):
    with patch.object(Path, "resolve", side_effect=OSError("denied")):
        assert _is_under_roots("some/relative.pdf", [tmp_path]) is False
    assert any("Cannot resolve" in message for message in _warnings(caplog))


def test_reset_collection_tolerates_a_missing_collection(tmp_path):
    client = chromadb.PersistentClient(path=str(tmp_path))
    collection = reset_collection(client, "fresh")
    assert collection.name == "fresh"


def test_reset_collection_recreates_an_existing_collection(tmp_path):
    client = chromadb.PersistentClient(path=str(tmp_path))
    first = get_or_create_collection(client, "docs")
    first.add(ids=["1"], documents=["text"], embeddings=[[0.1, 0.2, 0.3]])
    assert reset_collection(client, "docs").count() == 0


def test_reset_collection_does_not_hide_other_failures():
    client = MagicMock()
    client.delete_collection.side_effect = RuntimeError("storage down")
    with pytest.raises(RuntimeError):
        reset_collection(client, "docs")
