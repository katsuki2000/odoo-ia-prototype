"""Optional semantic retrieval of model candidates from instance labels."""

import logging
import math
import os
import weakref
from typing import Dict, List, Optional, Sequence, Tuple


logger = logging.getLogger(__name__)

SEMANTIC_CANDIDATE_LIMIT = 10
SEMANTIC_EMBEDDING_BATCH_SIZE = 64
SEMANTIC_RETRIEVAL_ENABLED_ENV = "RESOLVER_SEMANTIC_RETRIEVAL_ENABLED"
_SEMANTIC_INDEX_CACHE: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


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


def _embed_documents(embedding_function, documents: Sequence[str]) -> List[Sequence[float]]:
    embeddings = []
    for offset in range(0, len(documents), SEMANTIC_EMBEDDING_BATCH_SIZE):
        embeddings.extend(embedding_function(list(documents[offset:offset + SEMANTIC_EMBEDDING_BATCH_SIZE])))
    return embeddings


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) == 0:
        return 0.0
    numerator = sum(float(left_item) * float(right_item) for left_item, right_item in zip(left, right))
    left_norm = math.sqrt(sum(float(item) ** 2 for item in left))
    right_norm = math.sqrt(sum(float(item) ** 2 for item in right))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def rank_semantic_model_candidates(
    query: str,
    graph,
    embedding_function,
    *,
    language: Optional[str] = None,
    limit: int = SEMANTIC_CANDIDATE_LIMIT,
) -> List[str]:
    """Rank graph models by cosine similarity to their instance labels."""
    if not query or graph is None or limit <= 0:
        return []

    graph_cache = _SEMANTIC_INDEX_CACHE.setdefault(graph, {})
    cache_key = (language.casefold() if language else None, _embedding_name(embedding_function))
    cached_index = graph_cache.get(cache_key)
    if cached_index is None:
        documents = _model_documents(graph, language)
        if not documents:
            return []
        models, texts = zip(*documents)
        embeddings = _embed_documents(embedding_function, texts)
        if len(embeddings) != len(models):
            raise ValueError("Embedding provider returned an unexpected number of vectors.")
        cached_index = (models, embeddings)
        graph_cache[cache_key] = cached_index

    models, embeddings = cached_index
    query_embeddings = embedding_function([query])
    if len(query_embeddings) != 1:
        raise ValueError("Embedding provider returned an unexpected query vector count.")
    query_embedding = query_embeddings[0]
    ranked = sorted(
        (
            (model, _cosine_similarity(query_embedding, embedding))
            for model, embedding in zip(models, embeddings)
        ),
        key=lambda item: (-item[1], item[0]),
    )
    return [model for model, _score in ranked[:limit]]


def configured_semantic_model_candidates(
    query: str,
    graph,
    language: Optional[str],
    *,
    limit: int = SEMANTIC_CANDIDATE_LIMIT,
) -> List[str]:
    """Return semantic candidates unless explicitly disabled in the environment.

    Enabled by default: the retrieval only runs when an LLM is available for the
    bounded arbitration and fails open to the deterministic list on any error.
    """
    if os.getenv(SEMANTIC_RETRIEVAL_ENABLED_ENV, "true").casefold() not in {"1", "true", "yes"}:
        return []

    backend = os.getenv("RESOLVER_SEMANTIC_EMBEDDING_BACKEND") or os.getenv(
        "EMBEDDING_BACKEND", "local_light",
    )
    model = os.getenv("RESOLVER_SEMANTIC_EMBEDDING_MODEL") or os.getenv(
        "EMBEDDING_MODEL", "nomic-embed-text-v1.5",
    )
    try:
        from document_rag.vectorstore.embedding_functions import resolve_embedding_function

        embedding_function = resolve_embedding_function(backend=backend, embedding_model=model)
        if embedding_function is None:
            if backend == "local_light":
                from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

                embedding_function = DefaultEmbeddingFunction()
            else:
                logger.warning("Semantic retrieval is enabled but no embedding provider is configured.")
                return []
        return rank_semantic_model_candidates(
            query,
            graph,
            embedding_function,
            language=language,
            limit=limit,
        )
    except Exception:
        logger.exception("Semantic retrieval failed; keeping the deterministic candidate list.")
        return []
