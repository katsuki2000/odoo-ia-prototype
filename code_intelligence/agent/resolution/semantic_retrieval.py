"""Semantic retrieval with explicit provider identity and validated vectors."""

import hashlib
import json
import logging
import math
import os
import threading
import weakref
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit, urlunsplit

from config import settings
from .node_cards import build_node_cards
from .node_projection import ModelProjector
from .semantic_index_store import SemanticIndexStore, text_key

logger = logging.getLogger(__name__)
SEMANTIC_CANDIDATE_LIMIT = 15
INDEXED_NODE_TYPES = ('Model', 'Menu')
SEMANTIC_EMBEDDING_BATCH_SIZE = 64
SEMANTIC_RETRIEVAL_ENABLED_ENV = 'RESOLVER_SEMANTIC_RETRIEVAL_ENABLED'
SEMANTIC_STATUS_DIAGNOSTIC_KEY = 'semantic_retrieval'
_SEMANTIC_INDEX_CACHE = weakref.WeakKeyDictionary()
QUERY_EMBEDDING_CACHE_SIZE = 64
_QUERY_EMBEDDING_CACHE = {}
_CACHE_LOCK = threading.RLock()


class SemanticRetrievalStatus(str, Enum):
    SUCCESS = 'success'
    NO_CANDIDATES = 'no_candidates'
    DISABLED = 'disabled'
    ERROR = 'error'


@dataclass(frozen=True)
class SemanticRetrieval:
    models: List[str] = field(default_factory=list)
    status: SemanticRetrievalStatus = SemanticRetrievalStatus.NO_CANDIDATES


def _model_documents(graph, language=None) -> List[Tuple[str, str]]:
    """One document per model card and per menu card, each attributed to the models it opens."""
    projector = ModelProjector(graph)
    documents = []
    for card in build_node_cards(graph, language=language, node_types=INDEXED_NODE_TYPES):
        documents.extend((model.removeprefix('model:'), card.text) for model in projector(card.object_ref))
    return sorted(documents)


def _embedding_name(embedding_function) -> str:
    name = getattr(embedding_function, 'name', None)
    name = str(name() if callable(name) else type(embedding_function).__name__)
    endpoint = urlsplit(str(getattr(embedding_function, 'endpoint', '')))
    host = endpoint.hostname or ''
    if endpoint.port:
        host += ':' + str(endpoint.port)
    address = urlunsplit((endpoint.scheme, host, endpoint.path, '', ''))
    identity = [name, address, os.getenv('RESOLVER_SEMANTIC_EMBEDDING_REVISION', '')]
    return 'resolver-v2-' + hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def build_semantic_embedding_function():
    from config.settings import DEFAULT_EMBEDDING_BACKEND
    from document_rag.vectorstore.embedding_functions import resolve_embedding_function
    backend = (os.getenv('RESOLVER_SEMANTIC_EMBEDDING_BACKEND') or os.getenv('EMBEDDING_BACKEND', DEFAULT_EMBEDDING_BACKEND)).strip().lower()
    model = os.getenv('RESOLVER_SEMANTIC_EMBEDDING_MODEL')
    return resolve_embedding_function(backend=backend, embedding_model=model)


def _validated_vector(vector, dimension=None):
    values = tuple(float(value) for value in vector)
    if not values or (dimension is not None and len(values) != dimension):
        raise ValueError('Embedding dimension mismatch or empty vector.')
    if not all(math.isfinite(value) for value in values) or not any(values):
        raise ValueError('Embedding vector must be finite and nonzero.')
    return values


def _build_index(documents, embedding_function, index_store):
    models, texts = zip(*documents)
    keys = [text_key(text) for text in texts]
    stored = index_store.load() if index_store else {}
    vectors = {key: stored[key] for key in keys if key in stored}
    pending = [(key, text) for key, text in dict(zip(keys, texts)).items() if key not in vectors]
    for offset in range(0, len(pending), SEMANTIC_EMBEDDING_BATCH_SIZE):
        batch = pending[offset:offset + SEMANTIC_EMBEDDING_BATCH_SIZE]
        values = embedding_function([text for _key, text in batch])
        if len(values) != len(batch):
            raise ValueError('Embedding provider returned an unexpected vector count.')
        vectors.update((key, _validated_vector(vector)) for (key, _text), vector in zip(batch, values))
    dimension = len(_validated_vector(vectors[keys[0]]))
    matrix = [_validated_vector(vectors[key], dimension) for key in keys]
    if index_store and pending:
        index_store.save(dict(zip(keys, matrix)))
    return models, matrix


def _cosine_similarity(left, right):
    left = _validated_vector(left)
    right = _validated_vector(right, len(left))
    numerator = sum(a * b for a, b in zip(left, right))
    denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(sum(value * value for value in right))
    if not math.isfinite(numerator) or not math.isfinite(denominator) or not denominator:
        raise ValueError('Invalid cosine operands.')
    return max(-1.0, min(1.0, numerator / denominator))


def _query_embedding(embedding_function, query):
    key = (_embedding_name(embedding_function), query)
    with _CACHE_LOCK:
        cached = _QUERY_EMBEDDING_CACHE.get(key)
    if cached is not None:
        return cached
    values = embedding_function([query])
    if len(values) != 1:
        raise ValueError('Embedding provider returned an unexpected query count.')
    vector = _validated_vector(values[0])
    with _CACHE_LOCK:
        if len(_QUERY_EMBEDDING_CACHE) >= QUERY_EMBEDDING_CACHE_SIZE:
            _QUERY_EMBEDDING_CACHE.pop(next(iter(_QUERY_EMBEDDING_CACHE)))
        _QUERY_EMBEDDING_CACHE[key] = vector
    return vector


def rank_semantic_model_candidates_scored(query, graph, embedding_function, *, limit=SEMANTIC_CANDIDATE_LIMIT, cache_dir=None, language=None):
    if not query or graph is None or limit <= 0:
        return []
    documents = _model_documents(graph, language)
    if not documents:
        return []
    digest = hashlib.sha256(json.dumps(documents, ensure_ascii=False).encode()).hexdigest()
    identity = _embedding_name(embedding_function)
    with _CACHE_LOCK:
        cached = _SEMANTIC_INDEX_CACHE.setdefault(graph, {}).get(identity)
    if cached is None or cached[0] != digest:
        store = SemanticIndexStore(cache_dir, identity) if cache_dir else None
        cached = (digest, _build_index(documents, embedding_function, store))
        with _CACHE_LOCK:
            _SEMANTIC_INDEX_CACHE.setdefault(graph, {})[identity] = cached
    models, embeddings = cached[1]
    queryVector = _query_embedding(embedding_function, query)
    best = {}
    for model, vector in zip(models, embeddings):
        best[model] = max(best.get(model, -1.0), _cosine_similarity(queryVector, vector))
    return sorted(best.items(), key=lambda item: (-item[1], item[0]))[:limit]


def rank_semantic_model_candidates(query, graph, embedding_function, **options):
    return [model for model, _score in rank_semantic_model_candidates_scored(query, graph, embedding_function, **options)]


def retrieve_semantic_model_candidates_scored(query, graph, language, *, limit=SEMANTIC_CANDIDATE_LIMIT):
    if os.getenv(SEMANTIC_RETRIEVAL_ENABLED_ENV, 'true').casefold() not in {'1', 'true', 'yes'}:
        return [], SemanticRetrievalStatus.DISABLED
    try:
        provider = build_semantic_embedding_function()
        if provider is None:
            raise ValueError('No resolver embedding provider configured.')
        scored = rank_semantic_model_candidates_scored(query, graph, provider, limit=limit, cache_dir=settings.SEMANTIC_INDEX_CACHE_DIR, language=language)
        return scored, SemanticRetrievalStatus.SUCCESS if scored else SemanticRetrievalStatus.NO_CANDIDATES
    except Exception as error:
        logger.warning('Semantic retrieval unavailable (%s).', type(error).__name__)
        return [], SemanticRetrievalStatus.ERROR


def retrieve_semantic_model_candidates(query, graph, language, *, limit=SEMANTIC_CANDIDATE_LIMIT):
    scored, status = retrieve_semantic_model_candidates_scored(query, graph, language, limit=limit)
    return SemanticRetrieval([model for model, _score in scored], status)


def configured_semantic_model_candidates(query, graph, language, *, limit=SEMANTIC_CANDIDATE_LIMIT):
    return retrieve_semantic_model_candidates(query, graph, language, limit=limit).models


def warm_semantic_index(graph, languages):
    """Build the model index before the first question, one pass per language; failures stay statuses."""
    return [retrieve_semantic_model_candidates_scored('warm up', graph, language, limit=1)[1]
            for language in languages or [None]]
