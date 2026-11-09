"""Regression: the documentary index targets a single collection and never creates another (such as `odoo_code`)."""

from pathlib import Path

import chromadb

from config.settings import DOCS_COLLECTION_NAME
from document_rag.vectorstore.chroma_manager import ChromaManager


def _collection_names(db_path: Path) -> set[str]:
    client = chromadb.PersistentClient(path=str(db_path))
    return {getattr(collection, "name", collection) for collection in client.list_collections()}


def test_chroma_manager_defaults_to_the_documentary_collection(tmp_path):
    manager = ChromaManager(db_path=tmp_path)
    assert manager.collection_name == DOCS_COLLECTION_NAME
    assert _collection_names(tmp_path) == {DOCS_COLLECTION_NAME}


def test_chroma_manager_honors_its_collection_name(tmp_path):
    manager = ChromaManager(db_path=tmp_path, collection_name="custom")
    assert manager.collection_name == "custom"
    assert _collection_names(tmp_path) == {"custom"}
