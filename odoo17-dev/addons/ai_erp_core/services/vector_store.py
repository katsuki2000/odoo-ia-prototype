# -*- coding: utf-8 -*-
"""
vector_store.py
===============
Abstraction layer over ChromaDB for the AI ERP Core module.

Supports:
  - Upsert (add / update) chunks with metadata
  - Semantic similarity search returning top-K chunks with scores
  - Delete by IDs
  - Collection management (create / get)

ChromaDB is accessed via its HTTP client (chromadb.HttpClient) so the
vector store can run as a separate container (see docker-compose.yml).

If ChromaDB is not reachable or the package is not installed, every method
raises a clear VectorStoreError instead of a silent failure.
"""
import json
import logging
from typing import Any

_logger = logging.getLogger(__name__)

try:
    import chromadb
    _CHROMA_AVAILABLE = True
except ImportError:
    _CHROMA_AVAILABLE = False
    _logger.warning(
        'ai_erp_core: `chromadb` package not installed — vector store disabled.'
    )


class VectorStoreError(Exception):
    """Raised when a ChromaDB operation fails."""


class VectorStoreService:
    """
    Wraps a ChromaDB HTTP client for use by the ingestion and retriever services.

    Parameters
    ----------
    config : ai.config recordset
    """

    def __init__(self, config):
        self.config = config
        self._client = None

    # ── Connection ──────────────────────────────────────────────────────────────

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not _CHROMA_AVAILABLE:
            raise VectorStoreError(
                'Le package Python `chromadb` n\'est pas installé dans ce conteneur Odoo.'
            )
        try:
            self._client = chromadb.HttpClient(
                host=self.config.chromadb_host,
                port=self.config.chromadb_port,
            )
            # Lightweight heartbeat
            self._client.heartbeat()
        except Exception as exc:
            self._client = None
            raise VectorStoreError(f'Impossible de joindre ChromaDB : {exc}') from exc
        return self._client

    def _get_collection(self, collection_name: str):
        client = self._get_client()
        try:
            return client.get_or_create_collection(
                name=collection_name,
                metadata={'hnsw:space': 'cosine'},
            )
        except Exception as exc:
            raise VectorStoreError(
                f'Erreur lors de l\'accès à la collection « {collection_name} » : {exc}'
            ) from exc

    # ── Write ───────────────────────────────────────────────────────────────────

    def upsert_chunks(
        self,
        collection_name: str,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict],
    ) -> None:
        """
        Upsert a batch of text chunks with their embeddings.

        Parameters
        ----------
        collection_name : str
        ids             : unique string IDs for each chunk
        embeddings      : pre-computed embedding vectors
        documents       : raw text of each chunk
        metadatas       : metadata dicts (source, page, doc_id, etc.)
        """
        collection = self._get_collection(collection_name)
        try:
            collection.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas,
            )
        except Exception as exc:
            raise VectorStoreError(f'Erreur lors de l\'upsert : {exc}') from exc

    def delete_by_ids(self, collection_name: str, ids: list[str]) -> None:
        """Delete chunks by their IDs from a collection."""
        collection = self._get_collection(collection_name)
        try:
            collection.delete(ids=ids)
        except Exception as exc:
            raise VectorStoreError(f'Erreur lors de la suppression : {exc}') from exc

    # ── Read ────────────────────────────────────────────────────────────────────

    def search(
        self,
        collection_name: str,
        query_embedding: list[float],
        top_k: int = 5,
        where: dict | None = None,
    ) -> list[dict[str, Any]]:
        """
        Semantic similarity search.

        Parameters
        ----------
        collection_name  : str
        query_embedding  : the query embedding vector
        top_k            : number of results to return
        where            : optional ChromaDB metadata filter

        Returns
        -------
        List of dicts with keys:
          id, document, metadata, score  (cosine similarity, 0–1)
        """
        collection = self._get_collection(collection_name)
        try:
            kwargs: dict[str, Any] = {
                'query_embeddings': [query_embedding],
                'n_results': top_k,
                'include': ['documents', 'metadatas', 'distances'],
            }
            if where:
                kwargs['where'] = where
            results = collection.query(**kwargs)
        except Exception as exc:
            raise VectorStoreError(f'Erreur lors de la recherche : {exc}') from exc

        # Flatten the nested lists ChromaDB returns for a single query
        ids = results.get('ids', [[]])[0]
        documents = results.get('documents', [[]])[0]
        metadatas = results.get('metadatas', [[]])[0]
        distances = results.get('distances', [[]])[0]

        hits = []
        for chunk_id, doc, meta, dist in zip(ids, documents, metadatas, distances):
            # ChromaDB cosine distance: score = 1 - distance
            score = round(1.0 - float(dist), 4)
            hits.append({
                'id': chunk_id,
                'document': doc,
                'metadata': meta or {},
                'score': score,
            })
        return hits

    # ── Utility ─────────────────────────────────────────────────────────────────

    def count(self, collection_name: str) -> int:
        """Return the number of vectors in a collection."""
        try:
            collection = self._get_collection(collection_name)
            return collection.count()
        except VectorStoreError:
            return -1

    def test_connection(self) -> tuple[bool, str]:
        """Test ChromaDB connectivity."""
        try:
            client = self._get_client()
            hb = client.heartbeat()
            return True, f'ChromaDB OK — heartbeat {hb}'
        except VectorStoreError as exc:
            return False, str(exc)
