"""ChromaDB manager for vector storage and retrieval."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Optional

import chromadb
from config.settings import CHROMA_PATH, DOCS_COLLECTION_NAME
from document_rag.vectorstore.embedding_functions import resolve_embedding_function
from document_rag.vectorstore.chroma_helpers import clean_metadata, format_query_results

logger = logging.getLogger(__name__)
COLLECTION_METADATA = {'hnsw:space': 'cosine', 'description': 'Odoo document chunks'}


class ChromaManager:
    """Manage document chunks without changing backend defaults implicitly."""
    def __init__(self, db_path: str | Path = None, embedding_model: Optional[str] = None, collection_name: str = DOCS_COLLECTION_NAME):
        self.db_path = Path(db_path) if db_path is not None else Path(CHROMA_PATH)
        self.db_path.mkdir(parents=True, exist_ok=True)
        from config.settings import EMBEDDING_MODEL
        self.embedding_model = embedding_model or EMBEDDING_MODEL
        self.collection_name = collection_name
        self.client = chromadb.PersistentClient(path=str(self.db_path))
        self.collection = self.client.get_or_create_collection(name=collection_name,
            embedding_function=resolve_embedding_function(embedding_model=self.embedding_model),
            metadata=dict(COLLECTION_METADATA))

    def add_chunks(self, texts: list[str], metadatas: list[dict[str, Any]], ids: list[str] | None = None) -> list[str]:
        if not texts or not metadatas:
            return []
        if len(texts) != len(metadatas):
            raise ValueError('texts and metadatas must have the same length')
        if ids is None:
            ids = [f"{metadata.get('source', 'unknown')}_{index}_{hashlib.sha256(text.encode()).hexdigest()[:12]}"
                   for index, (text, metadata) in enumerate(zip(texts, metadatas))]
        self.collection.add(ids=ids, documents=texts, metadatas=[clean_metadata(metadata) for metadata in metadatas])
        return ids

    def query(self, query_text: str, top_k: int = 5, where: dict[str, Any] | None = None) -> dict[str, Any]:
        arguments = {'query_texts': [query_text], 'n_results': top_k}
        if where:
            arguments['where'] = where
        return format_query_results(self.collection.query(**arguments))

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
            type_stats = {}
            for doc_type in ['code_python', 'code_xml', 'code_js', 'code_csv', 'doc_pdf', 'doc_wiki']:
                try:
                    type_stats[doc_type] = len(self.collection.get(where={'type': {'$eq': doc_type}}, include=[]).get('ids', []))
                except Exception:
                    type_stats[doc_type] = 0
            module_stats = {}
            try:
                for metadata in self.collection.get(include=['metadatas']).get('metadatas', []):
                    module = metadata.get('module')
                    if module:
                        module_stats[module] = module_stats.get(module, 0) + 1
            except Exception as error:
                logger.warning('Module statistics unavailable (%s).', type(error).__name__)
            return {'total_chunks': len(rows.get('ids', [])), 'by_type': type_stats,
                    'by_module': module_stats, 'collection_name': self.collection_name}
        except Exception as error:
            return {'error': str(error), 'total_chunks': 0, 'by_type': {}, 'by_module': {}}

    def delete_collection(self) -> None:
        self.client.delete_collection(name=self.collection_name)
        self.collection = self.client.get_or_create_collection(name=self.collection_name,
            embedding_function=resolve_embedding_function(embedding_model=self.embedding_model),
            metadata=dict(COLLECTION_METADATA))
