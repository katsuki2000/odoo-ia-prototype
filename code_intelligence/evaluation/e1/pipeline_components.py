"""Real backends for the pipeline comparison (RapidFuzz, BM25, BGE, cross-encoder, LLM). Harness only.

Every backend is created on first use, so pipeline A and the BM25 stage run with no server, no model and no LLM.
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence

from code_intelligence.agent.matching import _fuzzy_match_graph
from code_intelligence.agent.text_normalization import normalize_query_text

from . import systems
from .arbitration import arbitrate as closed_list_arbitrate
from .cards import build_node_cards
from .config import load_e1_config
from .dense_index import resolve_e1_embedding_function
from .pipelines import Components
from .projection import ModelProjector, top_models

DEFAULT_RERANKER = "cross-encoder/ms-marco-MiniLM-L-6-v2"
DENSE_VARIANTS = ("e1", "production")
CARD_TEXT_LIMIT = 1500


def _lazy(factory: Callable):
    box: list = []

    def get():
        if not box:
            box.append(factory())
        return box[0]

    return get


def build_components(
    graph,
    *,
    dense_variant: str = "e1",
    reranker_model: str = DEFAULT_RERANKER,
    llm: Optional[Callable[[str, str], str]] = None,
    embedding_function=None,
    config: Optional[dict] = None,
) -> Components:
    if dense_variant not in DENSE_VARIANTS:
        raise ValueError(f"dense_variant must be one of {DENSE_VARIANTS}")
    config = config or load_e1_config()
    node_types = list(config.get("card_node_types") or ["Model", "Menu"])
    fuzzy_top_models = int(config.get("fuzzy_top_models", 10))
    bm25_top_models = int(config.get("bm25_top_models", 10))
    dense_top_models = int(config.get("dense_top_models", 10))
    projector = ModelProjector(graph)
    embed = _lazy(lambda: embedding_function or resolve_e1_embedding_function())
    llm_get = _lazy(lambda: llm or _default_llm())
    encoder = _lazy(lambda: _load_cross_encoder(reranker_model))
    texts: dict[str, dict[str, str]] = {}

    def card_texts(language: str) -> dict[str, str]:
        if language not in texts:
            cards = build_node_cards(graph, language=language, node_types=["Model"])
            texts[language] = {c.object_ref: " ".join(c.text.split()) for c in cards}
        return texts[language]

    def fuzzy(question: str, language: str) -> list[str]:
        clean = normalize_query_text(question.lower().strip())
        return [f"model:{name}" for name, _score in _fuzzy_match_graph(clean, graph, limit=fuzzy_top_models)]

    def bm25(question: str, language: str) -> list[str]:
        index = systems._bm25_index(graph, language, node_types)
        hits = index.search(question, top_k=len(index.cards))
        return top_models([h.object_ref for h in hits], projector, bm25_top_models)

    def dense(question: str, language: str) -> list[str]:
        if dense_variant == "production":
            from code_intelligence.agent.semantic_retrieval import (
                SemanticRetrievalStatus, retrieve_semantic_model_candidates_scored,
            )

            scored, status = retrieve_semantic_model_candidates_scored(question, graph, language, limit=dense_top_models)
            if status in (SemanticRetrievalStatus.ERROR, SemanticRetrievalStatus.DISABLED):
                raise RuntimeError(f"production semantic retrieval {status.value}")
            return [f"model:{name}" for name, _score in scored]
        function = embed()
        if function is None:
            raise RuntimeError("no embedding function resolved from env")
        index = systems._dense_index(
            graph, language, node_types, function, batch_size=int(config.get("dense_batch_size", 64)),
        )
        hits = index.search(question, function, top_k=len(index.cards), min_score=float(config.get("dense_min_score", 0.0)))
        return top_models([h.object_ref for h in hits], projector, dense_top_models)

    def rerank(question: str, language: str, refs: Sequence[str]) -> list[str]:
        if len(refs) < 2:
            return list(refs)
        by_ref = card_texts(language)
        pairs = [[question, by_ref.get(ref, ref)[:CARD_TEXT_LIMIT]] for ref in refs]
        scores = encoder().predict(pairs)
        order = sorted(range(len(refs)), key=lambda i: (-float(scores[i]), i))  # stable on ties
        return [refs[i] for i in order]

    def arbitrate(question: str, language: str, shortlist: Sequence[str]):
        by_ref = card_texts(language)
        return closed_list_arbitrate(question, [(ref, by_ref.get(ref, ref)) for ref in shortlist], llm_get())

    return Components(fuzzy=fuzzy, dense=dense, bm25=bm25, rerank=rerank, arbitrate=arbitrate)


def _default_llm():
    from .llm import resolve_e1_llm_callable

    return resolve_e1_llm_callable()


def _load_cross_encoder(model_name: str):
    from sentence_transformers import CrossEncoder

    try:
        return CrossEncoder(model_name, local_files_only=True)
    except Exception:  # not cached: retry online
        return CrossEncoder(model_name)
