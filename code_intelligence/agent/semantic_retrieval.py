"""Optional semantic retrieval of model candidates from instance labels."""

import logging
import math
import os
import time
import weakref
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

from config import settings

from .semantic_index_store import SemanticIndexStore, text_key


logger = logging.getLogger(__name__)

SEMANTIC_CANDIDATE_LIMIT = 10
SEMANTIC_EMBEDDING_BATCH_SIZE = 64
SEMANTIC_RETRIEVAL_ENABLED_ENV = "RESOLVER_SEMANTIC_RETRIEVAL_ENABLED"
SEMANTIC_STATUS_DIAGNOSTIC_KEY = "semantic_retrieval"
_SEMANTIC_INDEX_CACHE: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
QUERY_EMBEDDING_CACHE_SIZE = 64
_QUERY_EMBEDDING_CACHE: Dict[Tuple[str, str], Sequence[float]] = {}


class SemanticRetrievalStatus(str, Enum):
    SUCCESS = "success"
    NO_CANDIDATES = "no_candidates"
    DISABLED = "disabled"
    ERROR = "error"


@dataclass(frozen=True)
class SemanticRetrieval:
    models: List[str] = field(default_factory=list)
    status: SemanticRetrievalStatus = SemanticRetrievalStatus.NO_CANDIDATES


def _language_matches(candidate_language: object, language: Optional[str]) -> bool:
    if not language:
        return True
    candidate_base = str(candidate_language or "").casefold().split("_", 1)[0]
    language_base = language.casefold().split("_", 1)[0]
    return not candidate_base or candidate_base == language_base


def _node_labels(data: Dict, language: Optional[str]) -> List[str]:
    labels = []
    description = str(data.get("description") or data.get("label") or data.get("name") or "").strip()
    if description:
        labels.append(description)
    for translation in data.get("business_labels", []):
        label = str(translation.get("label") or "").strip()
        if label and _language_matches(translation.get("language"), language):
            labels.append(label)
    return list(dict.fromkeys(labels))


def _model_documents(graph, language: Optional[str]) -> List[Tuple[str, str]]:
    menu_labels: Dict[str, List[str]] = {}
    for node_id, data in graph.nodes(data=True):
        if data.get("node_type") != "Menu":
            continue
        labels = _node_labels(data, language)
        if not labels:
            continue
        for successor in graph.successors(node_id):
            if graph.edges[node_id, successor].get("edge_type") != "OPENS_MODEL":
                continue
            model = successor.removeprefix("model:")
            menu_labels.setdefault(model, []).extend(labels)

    documents = []
    for node_id, data in graph.nodes(data=True):
        if data.get("node_type") != "Model":
            continue
        model = str(data.get("name") or node_id.removeprefix("model:")).strip()
        labels = _node_labels(data, language)
        labels.extend(menu_labels.get(model, []))
        labels = list(dict.fromkeys(label for label in labels if label))
        if labels:
            documents.append((model, " ; ".join(labels)))
    return sorted(documents)


def _embedding_name(embedding_function) -> str:
    name = getattr(embedding_function, "name", None)
    return str(name() if callable(name) else type(embedding_function).__name__)


def build_semantic_embedding_function():
    """Embedding function of the semantic step (RESOLVER_SEMANTIC_* env, EMBEDDING_* fallback).

    None when no provider is configured for a backend other than local_light.
    """
    from document_rag.vectorstore.embedding_functions import resolve_embedding_function

    backend = os.getenv("RESOLVER_SEMANTIC_EMBEDDING_BACKEND") or os.getenv(
        "EMBEDDING_BACKEND", "local_light",
    )
    model = os.getenv("RESOLVER_SEMANTIC_EMBEDDING_MODEL") or os.getenv("EMBEDDING_MODEL")
    embedding_function = resolve_embedding_function(backend=backend, embedding_model=model)
    if embedding_function is None and backend == "local_light":
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

        return DefaultEmbeddingFunction()
    return embedding_function


def _build_index(
    documents: Sequence[Tuple[str, str]],
    embedding_function,
    index_store: Optional[SemanticIndexStore],
) -> Tuple[Sequence[str], List[Sequence[float]]]:
    """Embed only the texts missing from the store, saving progress even on failure."""
    models, texts = zip(*documents)
    keys = [text_key(text) for text in texts]
    vectors = index_store.load() if index_store else {}
    pending = [(key, text) for key, text in dict(zip(keys, texts)).items() if key not in vectors]
    started = time.perf_counter()
    try:
        for offset in range(0, len(pending), SEMANTIC_EMBEDDING_BATCH_SIZE):
            batch = pending[offset:offset + SEMANTIC_EMBEDDING_BATCH_SIZE]
            batch_vectors = embedding_function([text for _key, text in batch])
            if len(batch_vectors) != len(batch):
                raise ValueError("Embedding provider returned an unexpected number of vectors.")
            vectors.update(zip((key for key, _text in batch), batch_vectors))
    finally:
        if index_store and pending:
            index_store.save(vectors)
    logger.info(
        "Semantic index ready: %d models, %d embedded, %d reused, %.1fs",
        len(models), len(pending), len(set(keys)) - len(pending), time.perf_counter() - started,
    )
    return models, [vectors[key] for key in keys]


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) == 0:
        return 0.0
    numerator = sum(float(left_item) * float(right_item) for left_item, right_item in zip(left, right))
    left_norm = math.sqrt(sum(float(item) ** 2 for item in left))
    right_norm = math.sqrt(sum(float(item) ** 2 for item in right))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def _query_embedding(embedding_function, query: str):
    key = (_embedding_name(embedding_function), query)
    cached = _QUERY_EMBEDDING_CACHE.get(key)
    if cached is not None:
        return cached
    query_embeddings = embedding_function([query])
    if len(query_embeddings) != 1:
        raise ValueError("Embedding provider returned an unexpected query vector count.")
    if len(_QUERY_EMBEDDING_CACHE) >= QUERY_EMBEDDING_CACHE_SIZE:
        _QUERY_EMBEDDING_CACHE.pop(next(iter(_QUERY_EMBEDDING_CACHE)))
    _QUERY_EMBEDDING_CACHE[key] = query_embeddings[0]
    return query_embeddings[0]


def rank_semantic_model_candidates_scored(
    query: str,
    graph,
    embedding_function,
    *,
    language: Optional[str] = None,
    limit: int = SEMANTIC_CANDIDATE_LIMIT,
    cache_dir: Optional[str] = None,
) -> List[Tuple[str, float]]:
    """Rank graph models by cosine similarity to their instance labels.

    With cache_dir, document embeddings persist on disk across processes.
    """
    if not query or graph is None or limit <= 0:
        return []

    graph_cache = _SEMANTIC_INDEX_CACHE.setdefault(graph, {})
    embedding_name = _embedding_name(embedding_function)
    cache_key = (language.casefold() if language else None, embedding_name)
    cached_index = graph_cache.get(cache_key)
    if cached_index is None:
        documents = _model_documents(graph, language)
        if not documents:
            return []
        index_store = SemanticIndexStore(cache_dir, embedding_name) if cache_dir else None
        cached_index = _build_index(documents, embedding_function, index_store)
        graph_cache[cache_key] = cached_index

    models, embeddings = cached_index
    query_embedding = _query_embedding(embedding_function, query)
    ranked = sorted(
        (
            (model, _cosine_similarity(query_embedding, embedding))
            for model, embedding in zip(models, embeddings)
        ),
        key=lambda item: (-item[1], item[0]),
    )
    return [(model, score) for model, score in ranked[:limit]]


def rank_semantic_model_candidates(query: str, graph, embedding_function, **options) -> List[str]:
    return [
        model
        for model, _score in rank_semantic_model_candidates_scored(
            query, graph, embedding_function, **options,
        )
    ]


def retrieve_semantic_model_candidates(
    query: str,
    graph,
    language: Optional[str],
    *,
    limit: int = SEMANTIC_CANDIDATE_LIMIT,
) -> SemanticRetrieval:
    """Return semantic candidates with an explicit outcome, failing open on any error.

    Enabled by default; the caller keeps its deterministic list whatever the status.
    """
    if os.getenv(SEMANTIC_RETRIEVAL_ENABLED_ENV, "true").casefold() not in {"1", "true", "yes"}:
        return SemanticRetrieval(status=SemanticRetrievalStatus.DISABLED)

    try:
        embedding_function = build_semantic_embedding_function()
        if embedding_function is None:
            logger.warning("Semantic retrieval is enabled but no embedding provider is configured.")
            return SemanticRetrieval(status=SemanticRetrievalStatus.ERROR)
        models = rank_semantic_model_candidates(
            query,
            graph,
            embedding_function,
            language=language,
            limit=limit,
            cache_dir=settings.SEMANTIC_INDEX_CACHE_DIR,
        )
    except Exception:
        logger.exception("Semantic retrieval failed; keeping the deterministic candidate list.")
        return SemanticRetrieval(status=SemanticRetrievalStatus.ERROR)
    status = SemanticRetrievalStatus.SUCCESS if models else SemanticRetrievalStatus.NO_CANDIDATES
    return SemanticRetrieval(models, status)


def retrieve_semantic_model_candidates_scored(
    query: str,
    graph,
    language: Optional[str],
    *,
    limit: int = SEMANTIC_CANDIDATE_LIMIT,
) -> Tuple[List[Tuple[str, float]], SemanticRetrievalStatus]:
    """Return (model, score) pairs with retrieval status. Fails open on errors."""
    if os.getenv(SEMANTIC_RETRIEVAL_ENABLED_ENV, "true").casefold() not in {"1", "true", "yes"}:
        return [], SemanticRetrievalStatus.DISABLED

    try:
        embedding_function = build_semantic_embedding_function()
        if embedding_function is None:
            logger.warning("Semantic retrieval is enabled but no embedding provider is configured.")
            return [], SemanticRetrievalStatus.ERROR
        scored = rank_semantic_model_candidates_scored(
            query,
            graph,
            embedding_function,
            language=language,
            limit=limit,
            cache_dir=settings.SEMANTIC_INDEX_CACHE_DIR,
        )
    except Exception:
        logger.exception("Semantic retrieval failed; keeping the deterministic candidate list.")
        return [], SemanticRetrievalStatus.ERROR
    status = SemanticRetrievalStatus.SUCCESS if scored else SemanticRetrievalStatus.NO_CANDIDATES
    return scored, status


def configured_semantic_model_candidates(
    query: str,
    graph,
    language: Optional[str],
    *,
    limit: int = SEMANTIC_CANDIDATE_LIMIT,
) -> List[str]:
    """Return semantic candidates only; see retrieve_semantic_model_candidates for the outcome."""
    return retrieve_semantic_model_candidates(query, graph, language, limit=limit).models
