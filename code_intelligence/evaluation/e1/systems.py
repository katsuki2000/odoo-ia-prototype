"""E1 resolution systems. R0/R1 reuse the production resolver offline (llm=None).

R2+ (BM25/BGE/RRF/expansion) live only in this package and must not be imported
by the agent loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from code_intelligence.agent.resolver import resolve_business_term

from .bm25_index import Bm25CardIndex
from .cases import E1Case
from .config import load_e1_config
from .dense_index import DenseCardIndex, resolve_e1_embedding_function

# Per-graph BM25 indexes keyed by (id(graph), language, node_types)
_BM25_CACHE: dict[tuple[int, str, tuple[str, ...]], Bm25CardIndex] = {}
# Dense indexes keyed by (id(graph), language, node_types, embedding_name)
_DENSE_CACHE: dict[tuple[int, str, tuple[str, ...], str], DenseCardIndex] = {}


@dataclass(frozen=True)
class SystemOutput:
    system_id: str
    candidates: tuple[str, ...]
    declared_ambiguous: bool
    is_resolved: bool
    diagnostics: dict[str, Any]


def _from_resolved(system_id: str, concept) -> SystemOutput:
    models = tuple(concept.resolved_models or ())
    ambiguous = (not concept.is_resolved and len(models) >= 2) or (
        "ambig" in (concept.reason or "").casefold()
    )
    return SystemOutput(
        system_id=system_id,
        candidates=models,
        declared_ambiguous=ambiguous,
        is_resolved=bool(concept.is_resolved),
        diagnostics={
            "source_step": concept.source_step,
            "reason": concept.reason,
            "confidence": concept.confidence,
        },
    )


def run_r0(case: E1Case, graph, *, language: Optional[str] = None) -> SystemOutput:
    """Production resolver with static aliases."""
    concept = resolve_business_term(
        case.question,
        graph,
        llm=None,
        language=language or case.language,
        use_static_aliases=True,
    )
    return _from_resolved("R0", concept)


def run_r1(case: E1Case, graph, *, language: Optional[str] = None) -> SystemOutput:
    """Production resolver without static aliases (P4 ablation)."""
    concept = resolve_business_term(
        case.question,
        graph,
        llm=None,
        language=language or case.language,
        use_static_aliases=False,
    )
    return _from_resolved("R1", concept)


def _bm25_index(graph, language: Optional[str], node_types: list[str]) -> Bm25CardIndex:
    cache_key = (id(graph), str(language or ""), tuple(node_types))
    cached = _BM25_CACHE.get(cache_key)
    if cached is not None:
        return cached
    index = Bm25CardIndex.build(graph, language=language, node_types=node_types)
    _BM25_CACHE[cache_key] = index
    return index


def run_r2(case: E1Case, graph, *, language: Optional[str] = None, config: Optional[dict] = None) -> SystemOutput:
    """Lexicon-bearing node cards + BM25 (no embeddings, no LLM)."""
    config = config or load_e1_config()
    lang = language or case.language
    node_types = list(config.get("card_node_types") or ["Model", "Menu"])
    top_k = int(config.get("bm25_top_k", 10))
    ratio = float(config.get("bm25_ambiguity_score_ratio", 0.85))
    min_score = float(config.get("bm25_min_score", 0.0))

    index = _bm25_index(graph, lang, node_types)
    hits = [hit for hit in index.search(case.question, top_k=top_k) if hit.score > min_score]

    if not hits:
        return SystemOutput(
            system_id="R2",
            candidates=(),
            declared_ambiguous=False,
            is_resolved=False,
            diagnostics={"source_step": "bm25_empty", "reason": "No positive BM25 hit."},
        )

    ambiguous = False
    if len(hits) >= 2 and hits[0].score > 0:
        ambiguous = (hits[1].score / hits[0].score) >= ratio

    # Prefer returning model refs first when scores are tied family-wise; keep BM25 order.
    candidates = tuple(hit.object_ref for hit in hits)
    return SystemOutput(
        system_id="R2",
        candidates=candidates,
        declared_ambiguous=ambiguous,
        is_resolved=not ambiguous and bool(candidates),
        diagnostics={
            "source_step": "bm25_cards",
            "reason": f"BM25 top={hits[0].object_ref} score={hits[0].score:.4f}",
            "scores": {hit.object_ref: hit.score for hit in hits[:5]},
            "card_count": len(index.cards),
        },
    )


def _dense_index(
    graph,
    language: Optional[str],
    node_types: list[str],
    embedding_function,
    *,
    batch_size: int,
    cache_dir: Optional[str] = None,
) -> DenseCardIndex:
    name = getattr(embedding_function, "name", None)
    embedding_name = str(name() if callable(name) else name or type(embedding_function).__name__)
    cache_key = (id(graph), str(language or ""), tuple(node_types), embedding_name)
    cached = _DENSE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    index = DenseCardIndex.build(
        graph,
        embedding_function,
        language=language,
        node_types=node_types,
        batch_size=batch_size,
        cache_dir=cache_dir,
    )
    _DENSE_CACHE[cache_key] = index
    return index


def run_r3(
    case: E1Case,
    graph,
    *,
    language: Optional[str] = None,
    config: Optional[dict] = None,
    embedding_function=None,
) -> SystemOutput:
    """Node cards + dense embeddings (BGE-M3 when configured). No LLM."""
    config = config or load_e1_config()
    lang = language or case.language
    node_types = list(config.get("card_node_types") or ["Model", "Menu"])
    top_k = int(config.get("dense_top_k", config.get("bm25_top_k", 10)))
    ratio = float(config.get("dense_ambiguity_score_ratio", config.get("bm25_ambiguity_score_ratio", 0.85)))
    min_score = float(config.get("dense_min_score", 0.0))
    batch_size = int(config.get("dense_batch_size", 64))

    if embedding_function is None:
        embedding_function = resolve_e1_embedding_function()
    if embedding_function is None:
        raise RuntimeError("R3 requires an embedding function; none resolved from env.")

    index = _dense_index(
        graph, lang, node_types, embedding_function, batch_size=batch_size,
    )
    hits = index.search(
        case.question,
        embedding_function,
        top_k=top_k,
        min_score=min_score,
    )

    if not hits:
        return SystemOutput(
            system_id="R3",
            candidates=(),
            declared_ambiguous=False,
            is_resolved=False,
            diagnostics={"source_step": "dense_empty", "reason": "No positive dense hit."},
        )

    ambiguous = False
    if len(hits) >= 2 and hits[0].score > 0:
        ambiguous = (hits[1].score / hits[0].score) >= ratio

    candidates = tuple(hit.object_ref for hit in hits)
    return SystemOutput(
        system_id="R3",
        candidates=candidates,
        declared_ambiguous=ambiguous,
        is_resolved=not ambiguous and bool(candidates),
        diagnostics={
            "source_step": "dense_cards",
            "reason": f"Dense top={hits[0].object_ref} score={hits[0].score:.4f}",
            "scores": {hit.object_ref: hit.score for hit in hits[:5]},
            "card_count": len(index.cards),
            "embedding_name": index.embedding_name,
        },
    )


def run_system(
    system_id: str,
    case: E1Case,
    graph,
    *,
    language: Optional[str] = None,
    config: Optional[dict] = None,
    embedding_function=None,
) -> SystemOutput:
    if system_id == "R0":
        return run_r0(case, graph, language=language)
    if system_id == "R1":
        return run_r1(case, graph, language=language)
    if system_id == "R2":
        return run_r2(case, graph, language=language, config=config)
    if system_id == "R3":
        return run_r3(
            case, graph, language=language, config=config, embedding_function=embedding_function,
        )
    if system_id in {"R4", "R5"}:
        raise NotImplementedError(
            f"{system_id} (RRF/expansion) is not implemented yet; "
            "see todo/contexte.txt section 1227 / 1258"
        )
    raise ValueError(f"unknown E1 system: {system_id}")
