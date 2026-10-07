from config.settings import DOCS_COLLECTION_NAME
from document_rag.vectorstore.chroma_manager import COLLECTION_METADATA, ChromaManager


def test_new_collection_carries_only_the_shared_metadata(tmp_path):
    manager = ChromaManager(db_path=tmp_path)
    assert manager.collection.metadata == COLLECTION_METADATA


def test_recreated_collection_carries_the_same_metadata(tmp_path):
    manager = ChromaManager(db_path=tmp_path)
    manager.delete_collection()
    assert manager.collection.metadata == COLLECTION_METADATA


def test_stats_do_not_report_an_embedding_model(tmp_path):
    stats = ChromaManager(db_path=tmp_path).get_stats()
    assert "embedding_model" not in stats
    assert stats["collection_name"] == DOCS_COLLECTION_NAME
