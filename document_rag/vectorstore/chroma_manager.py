"""ChromaDB Manager for vector storage and retrieval."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_ROOT / ".env")

import chromadb
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

from config.settings import CHROMA_PATH
from document_rag.vectorstore.embedding_functions import (
    CustomNomicEmbeddingFunction,
    LocalNomicEmbeddingFunction,
    LocalServerEmbeddingFunction,
    resolve_embedding_function,
)
from document_rag.vectorstore.chroma_helpers import (
    clean_metadata,
    format_query_results,
    get_chroma_client,
    get_or_create_collection,
    add_documents,
    query_collection,
    reset_collection,
    get_collection_stats,
)

logger = logging.getLogger(__name__)


class ChromaManager:
    """Manages ChromaDB vector store for document and code chunks."""

    def __init__(
        self,
        db_path: str | Path = None,
        embedding_model: Optional[str] = None,
        collection_name: str = "odoo_documents",
    ):
        target_path = Path(db_path) if db_path is not None else Path(CHROMA_PATH)
        self.db_path = target_path
        self.db_path.mkdir(parents=True, exist_ok=True)
        from config.settings import EMBEDDING_MODEL_NAME
        self.embedding_model = embedding_model or os.getenv("EMBEDDING_MODEL") or EMBEDDING_MODEL_NAME
        self.collection_name = collection_name

        self.client = chromadb.PersistentClient(path=str(self.db_path))
        embedding_function = self._resolve_embedding_function()

        col_metadata = {
            "hnsw:space": "cosine",
            "description": "Odoo documents and code chunks",
        }
        if self.embedding_model:
            col_metadata["embedding_model"] = str(self.embedding_model)

        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=embedding_function,
            metadata=col_metadata,
        )
        logger.info("ChromaDB initialized at %s with collection '%s'", self.db_path, collection_name)

    def _resolve_embedding_function(self) -> Optional[EmbeddingFunction]:
        return resolve_embedding_function(embedding_model=self.embedding_model)

    def add_chunks(
        self,
        texts: list[str],
        metadatas: list[dict[str, Any]],
        ids: list[str] | None = None,
    ) -> list[str]:
        if not texts or not metadatas:
            logger.warning("Empty texts or metadatas provided to add_chunks")
            return []

        if len(texts) != len(metadatas):
            raise ValueError("texts and metadatas must have the same length")

        if ids is None:
            ids = []
            for i, text in enumerate(texts):
                content_hash = hashlib.sha256(text.encode()).hexdigest()[:12]
                source = metadatas[i].get("source", "unknown")
                ids.append(f"{source}_{i}_{content_hash}")

        cleaned_metadatas = [self._clean_metadata(m) for m in metadatas]
        try:
            self.collection.add(ids=ids, documents=texts, metadatas=cleaned_metadatas)
            logger.info("Added %d chunks to ChromaDB", len(texts))
            return ids
        except Exception as e:
            logger.error("Error adding chunks to ChromaDB: %s", e)
            raise

    def query(
        self,
        query_text: str,
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            kwargs = {"query_texts": [query_text], "n_results": top_k}
            if where:
                kwargs["where"] = where
            results = self.collection.query(**kwargs)
            return self._format_query_results(results)
        except Exception as e:
            logger.error("Error querying ChromaDB: %s", e)
            raise

    def get_by_id(self, chunk_id: str) -> dict[str, Any] | None:
        try:
            results = self.collection.get(ids=[chunk_id])
            if results and results["ids"]:
                return {
                    "id": results["ids"][0],
                    "document": results["documents"][0],
                    "metadata": results["metadatas"][0],
                }
            return None
        except Exception as e:
            logger.error("Error retrieving chunk %s: %s", chunk_id, e)
            return None

    def delete_by_source(self, source_path: str) -> int:
        try:
            results = self.collection.get(
                where={"source": {"$eq": source_path}},
                include=[],
            )
            if results and results["ids"]:
                chunk_ids = results["ids"]
                self.collection.delete(ids=chunk_ids)
                logger.info("Deleted %d chunks from source %s", len(chunk_ids), source_path)
                return len(chunk_ids)
            return 0
        except Exception as e:
            logger.error("Error deleting chunks from source %s: %s", source_path, e)
            raise

    def delete_by_ids(self, ids: list[str]) -> int:
        if not ids:
            return 0
        try:
            self.collection.delete(ids=ids)
            logger.info("Deleted %d chunks", len(ids))
            return len(ids)
        except Exception as e:
            logger.error("Error deleting chunks: %s", e)
            raise

    def get_stats(self) -> dict[str, Any]:
        try:
            all_docs = self.collection.get(include=[])
            total_chunks = len(all_docs.get("ids", []))

            type_stats = {}
            for doc_type in ["code_python", "code_xml", "code_js", "code_csv", "doc_pdf", "doc_wiki"]:
                try:
                    results = self.collection.get(where={"type": {"$eq": doc_type}}, include=[])
                    type_stats[doc_type] = len(results.get("ids", []))
                except Exception:
                    type_stats[doc_type] = 0

            module_stats = {}
            try:
                results = self.collection.get(include=["metadatas"])
                for metadata in results.get("metadatas", []):
                    module = metadata.get("module")
                    if module:
                        module_stats[module] = module_stats.get(module, 0) + 1
            except Exception:
                pass

            return {
                "total_chunks": total_chunks,
                "by_type": type_stats,
                "by_module": module_stats,
                "collection_name": self.collection_name,
                "embedding_model": self.embedding_model,
            }
        except Exception as e:
            logger.error("Error getting collection stats: %s", e)
            return {"error": str(e), "total_chunks": 0, "by_type": {}, "by_module": {}}

    def delete_collection(self) -> None:
        try:
            self.client.delete_collection(name=self.collection_name)
            logger.info("Deleted collection %s", self.collection_name)
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=self._resolve_embedding_function(),
                metadata={
                    "embedding_model": self.embedding_model,
                    "hnsw:space": "cosine",
                    "description": "Odoo documents and code chunks",
                },
            )
        except Exception as e:
            logger.error("Error deleting collection: %s", e)
            raise

    @staticmethod
    def _clean_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        return clean_metadata(metadata)

    @staticmethod
    def _format_query_results(raw_results: dict[str, Any]) -> dict[str, Any]:
        return format_query_results(raw_results)


if __name__ == "__main__":
    client = get_chroma_client()
    collection = get_or_create_collection(client)
    stats = get_collection_stats(collection)
    print(f"Collection '{stats['name']}': {stats['document_count']} documents")
