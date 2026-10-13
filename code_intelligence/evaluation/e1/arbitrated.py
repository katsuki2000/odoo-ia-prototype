"""R6: R4 candidates projected on models, then a closed-list LLM arbitration (harness only)."""

from __future__ import annotations

from typing import Optional

from . import hybrid, systems
from .arbitration import ArbitrationStatus, LlmCallable, arbitrate
from .cards import build_node_cards
from .cases import E1Case
from .config import load_e1_config
from .projection import ModelProjector, project_candidates

_PROJECTORS: dict[int, ModelProjector] = {}
_MODEL_CARDS: dict[tuple[int, str], dict[str, str]] = {}


def _projector(graph) -> ModelProjector:
    projector = _PROJECTORS.get(id(graph))
    if projector is None:
        projector = _PROJECTORS[id(graph)] = ModelProjector(graph)
    return projector


def _model_annotations(graph, language: Optional[str]) -> dict[str, str]:
    key = (id(graph), str(language or ""))
    cached = _MODEL_CARDS.get(key)
    if cached is None:
        cards = build_node_cards(graph, language=language, node_types=["Model"])
        cached = _MODEL_CARDS[key] = {card.object_ref: " ".join(card.text.split()) for card in cards}
    return cached


def require_fixed_thresholds(config: dict) -> None:
    """R6 thresholds are fixed by pmm before the first computation (section 1282, point 5)."""
    criteria = (config.get("decision_criteria") or {}).get("R6") or {}
    if criteria.get("thresholds_fixed") is not True:
        raise RuntimeError(
            "R6 refused: decision_criteria.R6.thresholds_fixed is not true in the E1 configuration; "
            "pmm fixes the R6 thresholds before the first R6 computation."
        )


def run_r6(
    case: E1Case,
    graph,
    *,
    language: Optional[str] = None,
    config: Optional[dict] = None,
    embedding_function=None,
    llm: Optional[LlmCallable] = None,
) -> systems.SystemOutput:
    config = config or load_e1_config()
    require_fixed_thresholds(config)
    if llm is None:
        raise RuntimeError("R6 requires an LLM callable; none was provided.")
    lang = language or case.language
    top_k = int((config.get("arbitration") or {}).get("top_k", 5))

    retrieved = hybrid.run_r4(
        case, graph, language=lang, config=config, embedding_function=embedding_function,
    )
    shortlist = project_candidates(retrieved.candidates, _projector(graph))[:top_k]
    if not shortlist:
        return systems.SystemOutput(
            system_id="R6", candidates=(), declared_ambiguous=False, is_resolved=False,
            diagnostics={"arbitration_status": "NO_CANDIDATES", "shortlist": []},
        )

    annotations = _model_annotations(graph, lang)
    result = arbitrate(
        case.question, [(ref, annotations.get(ref, ref)) for ref in shortlist], llm,
    )
    chosen = result.status is ArbitrationStatus.CHOSEN
    ordered = (result.choice, *(ref for ref in shortlist if ref != result.choice)) if chosen else tuple(shortlist)
    return systems.SystemOutput(
        system_id="R6",
        candidates=ordered,
        declared_ambiguous=result.status is ArbitrationStatus.AMBIGUOUS,
        is_resolved=chosen,
        diagnostics={
            "arbitration_status": result.status.value,
            "raw_output": result.raw,
            "shortlist": list(shortlist),
            "llm_ms": round(result.duration_ms, 1),
            "r4_diagnostics": retrieved.diagnostics,
        },
    )
