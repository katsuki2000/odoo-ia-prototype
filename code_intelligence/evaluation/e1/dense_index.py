"""Dense (embedding) index over E1 node cards. Offline experiment only."""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

from .cards import NodeCard, build_node_cards

logger = logging.getLogger(__name__)

EmbeddingFn = Callable[[Sequence[str]], Sequence[Sequence[float]]]


@dataclass(frozen=True)
class DenseHit:
    object_ref: str
    score: float
    node_type: str


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) == 0:
        return 0.0
    numerator = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = math.sqrt(sum(float(a) ** 2 for a in left))
    right_norm = math.sqrt(sum(float(b) ** 2 for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _embedding_name(embedding_function) -> str:
    name = getattr(embedding_function, "name", None)
    if callable(name):
        return str(name())
    if name:
        return str(name)
    return type(embedding_function).__name__


def resolve_e1_embedding_function():
    """Same backend env as the production semantic resolver (BGE via tunnel when configured)."""
    backend = os.getenv("RESOLVER_SEMANTIC_EMBEDDING_BACKEND") or os.getenv(
        "EMBEDDING_BACKEND", "local_light",
    )
    model = os.getenv("RESOLVER_SEMANTIC_EMBEDDING_MODEL") or os.getenv(
        "EMBEDDING_MODEL", "nomic-embed-text-v1.5",
    )
    from document_rag.vectorstore.embedding_functions import resolve_embedding_function

    embedding_function = resolve_embedding_function(backend=backend, embedding_model=model)
    if embedding_function is None and backend == "local_light":
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

        embedding_function = DefaultEmbeddingFunction()
    return embedding_function


def _cache_dir() -> Optional[str]:
    configured = os.getenv("E1_DENSE_INDEX_CACHE_DIR")
    if configured:
        return configured
    try:
        from config import settings

        root = getattr(settings, "SEMANTIC_INDEX_CACHE_DIR", None)
        if root:
            return str(Path(root).parent / "active_e1_dense_index")
    except Exception:
        pass
    return None


@dataclass
class DenseCardIndex:
    cards: tuple[NodeCard, ...]
    vectors: tuple[tuple[float, ...], ...]
    embedding_name: str
    _language: Optional[str]

    @classmethod
    def build(
        cls,
        graph,
        embedding_function: EmbeddingFn,
        *,
        language: Optional[str] = None,
        node_types: Sequence[str] | None = None,
        batch_size: int = 64,
        cache_dir: Optional[str] = None,
    ) -> "DenseCardIndex":
        cards = tuple(
            build_node_cards(
                graph,
                language=language,
                node_types=node_types
                or ("Model", "Menu", "Field", "Method", "Group", "Rule", "Button"),
            )
        )
        if not cards:
            return cls(cards=(), vectors=(), embedding_name=_embedding_name(embedding_function), _language=language)

        name = _embedding_name(embedding_function)
        store = None
        if cache_dir is None:
            cache_dir = _cache_dir()
        if cache_dir:
            from code_intelligence.agent.semantic_index_store import SemanticIndexStore

            store = SemanticIndexStore(cache_dir, f"e1-dense:{name}")

        cached = store.load() if store else {}
        vectors_by_hash: dict[str, list[float]] = {}
        pending: list[tuple[str, str]] = []
        for card in cards:
            if card.text_hash in cached:
                vectors_by_hash[card.text_hash] = list(cached[card.text_hash])
            else:
                pending.append((card.text_hash, card.text))

        # Deduplicate identical card texts before calling the provider.
        unique_pending: dict[str, str] = {}
        for text_hash, text in pending:
            unique_pending.setdefault(text_hash, text)

        if unique_pending:
            keys = list(unique_pending)
            texts = [unique_pending[key] for key in keys]
            logger.info(
                "E1 dense index: embedding %d/%d cards (batch=%d, model=%s)",
                len(keys), len(cards), batch_size, name,
            )
            for offset in range(0, len(keys), batch_size):
                batch_keys = keys[offset:offset + batch_size]
                batch_texts = texts[offset:offset + batch_size]
                batch_vectors = list(embedding_function(batch_texts))
                if len(batch_vectors) != len(batch_keys):
                    raise ValueError("Embedding provider returned an unexpected number of vectors.")
                for key, vector in zip(batch_keys, batch_vectors):
                    vectors_by_hash[key] = [float(x) for x in vector]
            if store:
                cached.update(vectors_by_hash)
                store.save(cached)

        ordered = tuple(tuple(float(x) for x in vectors_by_hash[card.text_hash]) for card in cards)
        return cls(cards=cards, vectors=ordered, embedding_name=name, _language=language)

    def search(
        self,
        query: str,
        embedding_function: EmbeddingFn,
        *,
        top_k: int = 10,
        node_types: Sequence[str] | None = None,
        min_score: float = 0.0,
    ) -> list[DenseHit]:
        if not query or not self.cards:
            return []
        query_vectors = list(embedding_function([query]))
        if len(query_vectors) != 1:
            raise ValueError("Embedding provider returned an unexpected query vector count.")
        query_vector = query_vectors[0]
        allowed = set(node_types) if node_types else None
        ranked: list[DenseHit] = []
        for card, vector in zip(self.cards, self.vectors):
            if allowed is not None and card.node_type not in allowed:
                continue
            score = _cosine(query_vector, vector)
            if score <= min_score:
                continue
            ranked.append(
                DenseHit(object_ref=card.object_ref, score=float(score), node_type=card.node_type)
            )
        ranked.sort(key=lambda hit: (-hit.score, hit.object_ref))
        return ranked[:top_k]
