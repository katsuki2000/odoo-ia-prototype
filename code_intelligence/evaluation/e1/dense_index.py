"""Dense (embedding) index over E1 node cards. Offline experiment only."""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Sequence

import numpy as np

from .cards import NodeCard, build_node_cards

logger = logging.getLogger(__name__)

EmbeddingFn = Callable[[Sequence[str]], Sequence[Sequence[float]]]


@dataclass(frozen=True)
class DenseHit:
    object_ref: str
    score: float
    node_type: str


def _unit_rows(vectors) -> np.ndarray:
    """Float32 copy with every row scaled to unit length; all-zero rows stay zero."""
    matrix = np.array(vectors, dtype=np.float32)
    if matrix.size == 0:
        return np.zeros((0, 0), dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix /= np.where(norms > 0.0, norms, 1.0)
    return matrix


def _embedding_name(embedding_function) -> str:
    name = getattr(embedding_function, "name", None)
    if callable(name):
        return str(name())
    if name:
        return str(name)
    return type(embedding_function).__name__


def resolve_e1_embedding_function():
    """Same embedding provider as the production semantic resolver."""
    from code_intelligence.agent.semantic_retrieval import build_semantic_embedding_function

    return build_semantic_embedding_function()


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
    """Cards with one unit-length float32 row each; cosine similarity is a dot product."""

    cards: tuple[NodeCard, ...]
    vectors: np.ndarray
    embedding_name: str
    _language: Optional[str]
    _node_types: np.ndarray = field(init=False, repr=False)
    _ref_rank: np.ndarray = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.vectors = _unit_rows(self.vectors)
        self._node_types = np.array([card.node_type for card in self.cards])
        refs = np.array([card.object_ref for card in self.cards])
        self._ref_rank = np.unique(refs, return_inverse=True)[1]

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
        name = _embedding_name(embedding_function)
        if not cards:
            return cls(cards=(), vectors=np.empty((0, 0)), embedding_name=name, _language=language)

        store = None
        if cache_dir is None:
            cache_dir = _cache_dir()
        if cache_dir:
            from code_intelligence.agent.semantic_index_store import SemanticIndexStore

            store = SemanticIndexStore(cache_dir, f"e1-dense:{name}")

        stored_keys, stored = store.load_arrays() if store else ([], np.empty((0, 0), dtype=np.float32))
        known = set(stored_keys)
        # Identical card texts are embedded once.
        missing: dict[str, str] = {}
        for card in cards:
            if card.text_hash not in known:
                missing.setdefault(card.text_hash, card.text)

        if missing:
            keys = list(missing)
            batch_count = math.ceil(len(keys) / batch_size)
            logger.info(
                "E1 dense index: embedding %d/%d cards (batch=%d, model=%s)",
                len(keys), len(cards), batch_size, name,
            )
            for batch_number, offset in enumerate(range(0, len(keys), batch_size), start=1):
                batch_keys = keys[offset:offset + batch_size]
                logger.info(
                    "E1 dense index: batch %d/%d (%d cards embedded so far of %d)",
                    batch_number, batch_count, offset, len(keys),
                )
                batch = np.asarray(
                    embedding_function([missing[key] for key in batch_keys]), dtype=np.float32,
                )
                if batch.ndim != 2 or len(batch) != len(batch_keys):
                    raise ValueError("Embedding provider returned an unexpected number of vectors.")
                stored = batch if not stored_keys else np.concatenate((stored, batch))
                stored_keys.extend(batch_keys)
                if store:
                    # Persist after every successful batch: a provider failure on a later
                    # batch must not discard the vectors already computed.
                    store.save_arrays(stored_keys, stored)

        row_of = {key: row for row, key in enumerate(stored_keys)}
        rows = [row_of[card.text_hash] for card in cards]
        return cls(cards=cards, vectors=stored[rows], embedding_name=name, _language=language)

    def _scores(self, query_vector: Sequence[float]) -> np.ndarray:
        query = np.asarray(query_vector, dtype=np.float32)
        norm = float(np.linalg.norm(query)) if query.ndim == 1 else 0.0
        if query.shape != (self.vectors.shape[1],) or norm == 0.0:
            return np.zeros(len(self.cards), dtype=np.float32)
        return self.vectors @ (query / norm)

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
        scores = self._scores(query_vectors[0])
        eligible = scores > min_score
        if node_types:
            eligible &= np.isin(self._node_types, list(node_types))
        candidates = np.flatnonzero(eligible)
        order = np.lexsort((self._ref_rank[candidates], -scores[candidates]))
        return [
            DenseHit(
                object_ref=self.cards[row].object_ref,
                score=float(scores[row]),
                node_type=self.cards[row].node_type,
            )
            for row in candidates[order][:top_k]
        ]
