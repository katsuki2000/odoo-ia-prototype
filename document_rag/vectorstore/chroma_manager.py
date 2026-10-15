"""ChromaDB manager for vector storage and retrieval."""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Optional
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / '.env')
import chromadb
from chromadb.api.types import EmbeddingFunction
from config.settings import CHROMA_PATH, DOCS_COLLECTION_NAME
from document_rag.vectorstore.embedding_functions import resolve_embedding_function, SERVER_EMBEDDING_BACKENDS
from document_rag.vectorstore.chroma_helpers import (
    clean_metadata, format_query_results, get_chroma_client, get_or_create_collection,
    add_documents, reset_collection, get_collection_stats,
)

logger = logging.getLogger(__name__)
COLLECTION_METADATA = {'hnsw:space': 'cosine', 'description': 'Odoo document chunks'}


class ChromaManager:
    """Manage document chunks without changing backend defaults implicitly."""
    def __init__(self, db_path: str | Path = None, embedding_model: Optional[str] = None, collection_name: str = DOCS_COLLECTION_NAME):
        self.db_path = Path(db_path) if db_path is not None else Path(CHROMA_PATH)
        self.db_path.mkdir(parents=True, exist_ok=True)
        from config.settings import EMBEDDING_MODEL_NAME, LOCAL_EMBEDDING_MODEL
        backend = os.getenv('EMBEDDING_BACKEND', 'local_light').strip().lower()
        defaultModel = LOCAL_EMBEDDING_MODEL if backend in SERVER_EMBEDDING_BACKENDS else os.getenv('EMBEDDING_MODEL') or EMBEDDING_MODEL_NAME
        self.embedding_model = embedding_model or defaultModel
        self.collection_name = collection_name
        self.client = chromadb.PersistentClient(path=str(self.db_path))
        self.collection = self.client.get_or_create_collection(name=collection_name,
            embedding_function=self._resolve_embedding_function(), metadata=dict(COLLECTION_METADATA))

    def _resolve_embedding_function(self) -> Optional[EmbeddingFunction]:
        return resolve_embedding_function(embedding_model=self.embedding_model)

    def add_chunks(self, texts: list[str], metadatas: list[dict[str, Any]], ids: list[str] | None = None) -> list[str]:
        if not texts or not metadatas:
            return []
        if len(texts) != len(metadatas):
            raise ValueError('texts and metadatas must have the same length')
        if ids is None:
            ids = [f"{metadata.get('source', 'unknown')}_{index}_{hashlib.sha256(text.encode()).hexdigest()[:12]}"
                   for index, (text, metadata) in enumerate(zip(texts, metadatas))]
        self.collection.add(ids=ids, documents=texts, metadatas=[self._clean_metadata(metadata) for metadata in metadatas])
        return ids

    def query(self, query_text: str, top_k: int = 5, where: dict[str, Any] | None = None) -> dict[str, Any]:
        arguments = {'query_texts': [query_text], 'n_results': top_k}
        if where:
            arguments['where'] = where
        return self._format_query_results(self.collection.query(**arguments))

    def get_by_id(self, chunk_id: str) -> dict[str, Any] | None:
        try:
            rows = self.collection.get(ids=[chunk_id])
            if rows and rows['ids']:
                return {'id': rows['ids'][0], 'document': rows['documents'][0], 'metadata': rows['metadatas'][0]}
        except Exception as error:
            logger.error('Chunk lookup failed (%s).', type(error).__name__)
        return None

    def delete_by_source(self, source_path: str) -> int:
        rows = self.collection.get(where={'source': {'$eq': source_path}}, include=[])
        return self.delete_by_ids(rows.get('ids', []) if rows else [])

    def delete_by_ids(self, ids: list[str]) -> int:
        if ids:
            self.collection.delete(ids=ids)
        return len(ids)

    def get_stats(self) -> dict[str, Any]:
        try:
            rows = self.collection.get(include=[])
            typeStats = {}
            for docType in ['code_python', 'code_xml', 'code_js', 'code_csv', 'doc_pdf', 'doc_wiki']:
                try:
                    typeStats[docType] = len(self.collection.get(where={'type': {'$eq': docType}}, include=[]).get('ids', []))
                except Exception:
                    typeStats[docType] = 0
            moduleStats = {}
            try:
                for metadata in self.collection.get(include=['metadatas']).get('metadatas', []):
                    module = metadata.get('module')
                    if module:
                        moduleStats[module] = moduleStats.get(module, 0) + 1
            except Exception as error:
                logger.warning('Module statistics unavailable (%s).', type(error).__name__)
            return {'total_chunks': len(rows.get('ids', [])), 'by_type': typeStats,
                    'by_module': moduleStats, 'collection_name': self.collection_name}
        except Exception as error:
            return {'error': str(error), 'total_chunks': 0, 'by_type': {}, 'by_module': {}}

    def delete_collection(self) -> None:
        self.client.delete_collection(name=self.collection_name)
        self.collection = self.client.get_or_create_collection(name=self.collection_name,
            embedding_function=self._resolve_embedding_function(), metadata=dict(COLLECTION_METADATA))

    @staticmethod
    def _clean_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        return clean_metadata(metadata)

    @staticmethod
    def _format_query_results(raw_results: dict[str, Any]) -> dict[str, Any]:
        return format_query_results(raw_results)


if __name__ == '__main__':
    client = get_chroma_client()
    collection = get_or_create_collection(client)
    stats = get_collection_stats(collection)
    print(f"Collection '{stats['name']}': {stats['document_count']} documents")
