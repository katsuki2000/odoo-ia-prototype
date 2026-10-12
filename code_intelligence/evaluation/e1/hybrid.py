"""R4: reciprocal rank fusion of the BM25 (R2) and dense (R3) rankings."""

from __future__ import annotations

from typing import Optional

from . import systems
from .cases import E1Case
from .config import load_e1_config
from .fusion import reciprocal_rank_fusion


def run_r4(
    case: E1Case,
    graph,
    *,
    language: Optional[str] = None,
    config: Optional[dict] = None,
    embedding_function=None,
) -> systems.SystemOutput:
    """Hybrid retrieval without LLM.

    The fused list is the candidate generator. The case counts as resolved only
    when both retrievers rank the same reference first; any disagreement, or a
    single retriever answering alone, keeps that retriever's own ambiguity flag.
    """
    config = config or load_e1_config()
    lexical = systems.run_r2(case, graph, language=language, config=config)
    dense = systems.run_r3(
        case, graph, language=language, config=config, embedding_function=embedding_function,
    )

    fused = reciprocal_rank_fusion(
        {"bm25": lexical.candidates, "dense": dense.candidates},
        weights={
            "bm25": float(config.get("rrf_weight_bm25", 1.0)),
            "dense": float(config.get("rrf_weight_dense", 1.0)),
        },
        constant=int(config.get("rrf_constant", 60)),
    )
    candidates = tuple(ref for ref, _ in fused)

    if not candidates:
        return systems.SystemOutput(
            system_id="R4",
            candidates=(),
            declared_ambiguous=False,
            is_resolved=False,
            diagnostics={"source_step": "rrf_empty", "reason": "Neither retriever returned a hit."},
        )

    if lexical.candidates and dense.candidates:
        agreed = lexical.candidates[0] == dense.candidates[0]
        resolved, ambiguous = agreed, not agreed
        reason = "top-1 agreement" if agreed else "retrievers disagree on top-1"
    else:
        single = lexical if lexical.candidates else dense
        resolved, ambiguous = single.is_resolved, single.declared_ambiguous
        reason = f"only {single.system_id} returned hits"

    return systems.SystemOutput(
        system_id="R4",
        candidates=candidates,
        declared_ambiguous=ambiguous,
        is_resolved=resolved,
        diagnostics={
            "source_step": "rrf",
            "reason": reason,
            "scores": {ref: score for ref, score in fused[:5]},
            "bm25_top1": lexical.candidates[0] if lexical.candidates else None,
            "dense_top1": dense.candidates[0] if dense.candidates else None,
        },
    )
