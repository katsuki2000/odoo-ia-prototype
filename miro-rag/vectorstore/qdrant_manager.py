"""
Qdrant vector store manager.

Provides the same CRUD and query interface as ChromaManager so the retrieval
pipeline can switch backends without changing callers.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import uuid
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import QDRANT_URL

logger = logging.getLogger(__name__)

_MODEL_ALIASES = {
    "nomic-embed-text-v1.5": "nomic-ai/nomic-embed-text-v1.5",
    "all-MiniLM-L6-v2": "sentence-transformers/all-MiniLM-L6-v2",
}


class QdrantManager:
    """Manages Qdrant collections for document chunks."""

    def __init__(
        self,
        url: str | None = None,
        embedding_model: str = "nomic-embed-text-v1.5",
        collection_name: str = "odoo_documents",
        db_path: str | None = None,
        client: QdrantClient | None = None,
    ):
        """
        Initialize a Qdrant client and ensure the target collection exists.

        Args:
            url: Qdrant server URL. Use ":memory:" for in-process tests.
            embedding_model: Embedding model identifier stored in collection metadata.
            collection_name: Target Qdrant collection name.
            db_path: Legacy ChromaManager parameter kept for interface compatibility.
            client: Optional pre-built QdrantClient (for tests sharing one instance).
        """
        del db_path

        self.url = url or QDRANT_URL
        self.embedding_model = embedding_model
        self.collection_name = collection_name
        if client is not None:
            self.client = client
        elif self.url == ":memory:":
            self.client = QdrantClient(location=":memory:", timeout=30, check_compatibility=False)
        else:
            self.client = QdrantClient(url=self.url, timeout=30, check_compatibility=False)
        self._embedder = None
        self._vector_size: int | None = None

        self._ensure_collection()
        logger.info(
            "Qdrant initialized at %s with collection '%s'",
            self.url,
            self.collection_name,
        )

    @property
    def collection(self):
        """Compatibility shim for code that reads ChromaManager.collection."""
        return self

    @property
    def embedder(self):
        if self._embedder is None:
            from sentence_transformers import SentenceTransformer

            model_name = _MODEL_ALIASES.get(self.embedding_model, self.embedding_model)
            self._embedder = SentenceTransformer(
                model_name,
                trust_remote_code=True,
            )
            sample = self._embed_texts(["dimension probe"], is_query=False)
            self._vector_size = len(sample[0]) if sample else 384
        return self._embedder

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
            for index, text in enumerate(texts):
                content_hash = hashlib.sha256(text.encode()).hexdigest()[:12]
                source = metadatas[index].get("source", "unknown")
                ids.append(f"{source}_{index}_{content_hash}")

        cleaned_metadatas = [self._clean_metadata(metadata) for metadata in metadatas]
        self._ensure_vector_size()
        vectors = self._embed_texts(texts, is_query=False)

        points = []
        for chunk_id, text, metadata, vector in zip(ids, texts, cleaned_metadatas, vectors):
            payload = dict(metadata)
            payload["document"] = text
            payload["chunk_id"] = chunk_id
            points.append(
                PointStruct(
                    id=self._point_id(chunk_id),
                    vector=vector,
                    payload=payload,
                )
            )

        try:
            self.client.upsert(collection_name=self.collection_name, points=points)
            logger.info("Added %s chunks to Qdrant", len(texts))
            return ids
        except Exception as exc:
            logger.error("Error adding chunks to Qdrant: %s", exc)
            raise

    def query(
        self,
        query_text: str,
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            self._ensure_vector_size()
            query_vector = self._embed_texts([query_text], is_query=True)[0]
            qdrant_filter = self._build_filter(where)
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                limit=top_k,
                query_filter=qdrant_filter,
                with_payload=True,
            )
            hits = response.points
            return self._format_query_results(hits)
        except Exception as exc:
            logger.error("Error querying Qdrant: %s", exc)
            raise

    def get_by_id(self, chunk_id: str) -> dict[str, Any] | None:
        try:
            points = self.client.retrieve(
                collection_name=self.collection_name,
                ids=[self._point_id(chunk_id)],
                with_payload=True,
            )
            if not points:
                return None

            payload = points[0].payload or {}
            metadata = {
                key: value
                for key, value in payload.items()
                if key not in {"document", "chunk_id"}
            }
            return {
                "id": payload.get("chunk_id", chunk_id),
                "document": payload.get("document", ""),
                "metadata": metadata,
            }
        except Exception as exc:
            logger.error("Error retrieving chunk %s: %s", chunk_id, exc)
            return None

    def delete_by_source(self, source_path: str) -> int:
        try:
            chunk_ids = self._scroll_chunk_ids({"source": source_path})
            if not chunk_ids:
                return 0

            point_ids = [self._point_id(chunk_id) for chunk_id in chunk_ids]
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=point_ids,
            )
            logger.info("Deleted %s chunks from source %s", len(point_ids), source_path)
            return len(point_ids)
        except Exception as exc:
            logger.error("Error deleting chunks from source %s: %s", source_path, exc)
            raise

    def delete_by_ids(self, ids: list[str]) -> int:
        if not ids:
            return 0

        try:
            point_ids = [self._point_id(chunk_id) for chunk_id in ids]
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=point_ids,
            )
            logger.info("Deleted %s chunks", len(point_ids))
            return len(point_ids)
        except Exception as exc:
            logger.error("Error deleting chunks: %s", exc)
            raise

    def get_stats(self) -> dict[str, Any]:
        try:
            payloads = self._scroll_payloads()
            total_chunks = len(payloads)

            type_stats = {doc_type: 0 for doc_type in ["code_python", "code_xml", "doc_pdf", "doc_wiki"]}
            module_stats: dict[str, int] = {}

            for payload in payloads:
                doc_type = payload.get("type")
                if doc_type in type_stats:
                    type_stats[doc_type] += 1

                module = payload.get("module", "unknown")
                module_stats[module] = module_stats.get(module, 0) + 1

            return {
                "total_chunks": total_chunks,
                "by_type": type_stats,
                "by_module": module_stats,
                "collection_name": self.collection_name,
                "embedding_model": self.embedding_model,
            }
        except Exception as exc:
            logger.error("Error getting collection stats: %s", exc)
            return {
                "error": str(exc),
                "total_chunks": 0,
                "by_type": {},
                "by_module": {},
            }

    def delete_collection(self) -> None:
        try:
            if self.client.collection_exists(self.collection_name):
                self.client.delete_collection(self.collection_name)
                logger.info("Deleted collection %s", self.collection_name)
            self._ensure_collection()
        except Exception as exc:
            logger.error("Error deleting collection: %s", exc)
            raise

    def get(
        self,
        where: dict[str, Any] | None = None,
        include: list[str] | None = None,
    ) -> dict[str, list[Any]]:
        """Chroma-compatible bulk read used by BM25 indexing helpers."""
        del include
        payloads = self._scroll_payloads(where=where)
        ids = [payload.get("chunk_id", "") for payload in payloads]
        documents = [payload.get("document", "") for payload in payloads]
        metadatas = [
            {
                key: value
                for key, value in payload.items()
                if key not in {"document", "chunk_id"}
            }
            for payload in payloads
        ]
        return {
            "ids": ids,
            "documents": documents,
            "metadatas": metadatas,
        }

    @staticmethod
    def _clean_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}

        for key, value in metadata.items():
            if value is None:
                continue

            if isinstance(value, (str, int, float, bool)):
                cleaned[key] = value
            elif isinstance(value, (dict, list)):
                cleaned[key] = json.dumps(value)
            else:
                cleaned[key] = str(value)

        return cleaned

    @staticmethod
    def _point_id(chunk_id: str) -> str:
        try:
            return str(uuid.UUID(chunk_id))
        except ValueError:
            return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))

    def _ensure_collection(self) -> None:
        if self.client.collection_exists(self.collection_name):
            return

        self._ensure_vector_size()
        vector_size = self._vector_size or 384
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )

    def _ensure_vector_size(self) -> None:
        if self._vector_size is not None:
            return

        _ = self.embedder
        if self._vector_size is None:
            self._vector_size = 384

    def _embed_texts(self, texts: list[str], is_query: bool) -> list[list[float]]:
        if "nomic" in self.embedding_model.lower():
            prefix = "search_query: " if is_query else "search_document: "
            texts = [f"{prefix}{text}" for text in texts]
        else:
            _ = self.embedder

        vectors = self.embedder.encode(texts, normalize_embeddings=True)
        return vectors.tolist()

    @staticmethod
    def _build_filter(where: dict[str, Any] | None) -> Filter | None:
        if not where:
            return None

        conditions = []
        for field, clause in where.items():
            if isinstance(clause, dict) and "$eq" in clause:
                conditions.append(
                    FieldCondition(key=field, match=MatchValue(value=clause["$eq"]))
                )
            else:
                logger.warning("Unsupported Qdrant filter clause for field %s", field)

        if conditions:
            return Filter(must=conditions)
        return None

    def _scroll_payloads(self, where: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        qdrant_filter = self._build_filter(where)
        payloads: list[dict[str, Any]] = []
        offset = None

        while True:
            points, offset = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=qdrant_filter,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            if not points:
                break

            for point in points:
                if point.payload:
                    payloads.append(point.payload)

            if offset is None:
                break

        return payloads

    def _scroll_chunk_ids(self, where: dict[str, str]) -> list[str]:
        qdrant_filter = self._build_filter(
            {key: {"$eq": value} for key, value in where.items()}
        )
        chunk_ids: list[str] = []
        offset = None

        while True:
            points, offset = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=qdrant_filter,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            if not points:
                break

            for point in points:
                payload = point.payload or {}
                chunk_id = payload.get("chunk_id")
                if chunk_id:
                    chunk_ids.append(chunk_id)

            if offset is None:
                break

        return chunk_ids

    @staticmethod
    def _format_query_results(hits: list[Any]) -> dict[str, Any]:
        formatted = {
            "results": [],
            "count": 0,
        }

        if not hits:
            return formatted

        for hit in hits:
            payload = hit.payload or {}
            score = float(hit.score) if hit.score is not None else 0.0
            metadata = {
                key: value
                for key, value in payload.items()
                if key not in {"document", "chunk_id"}
            }
            formatted["results"].append(
                {
                    "id": payload.get("chunk_id", str(hit.id)),
                    "document": payload.get("document", ""),
                    "distance": 1.0 - score,
                    "similarity": score,
                    "metadata": metadata,
                }
            )

        formatted["count"] = len(formatted["results"])
        return formatted
