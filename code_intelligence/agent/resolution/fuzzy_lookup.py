"""Resolution step: fuzzy matching on graph labels with deterministic tie-break and bounded LLM arbitration."""

from typing import Dict, List, Optional, Sequence, Tuple

from ..matching import ResolvedConcept, _fuzzy_match_graph
from ..semantic_retrieval import SEMANTIC_STATUS_DIAGNOSTIC_KEY
from .arbitration import ArbitrationTrace, _llm_arbitrate
from .candidates import (
    AMBIGUITY_GAP_THRESHOLD,
    WIDENED_CANDIDATE_LIMIT,
    WIDENED_CANDIDATE_THRESHOLD,
    ArbitrationShortlist,
    _candidate_contexts,
    _deterministic_tiebreak,
    build_arbitration_shortlist,
)


def _arbitration_outcome(llm) -> str:
    return "LLM arbitration did not select one" if llm is not None else "no LLM was available for arbitration"


def _describe(fuzzy_results: List[Tuple[str, float]]) -> str:
    return ", ".join(f"{model} ({score:.0f})" for model, score in fuzzy_results)


AMBIGUOUS_CANDIDATES_KEY = "ambiguous_candidates"
ARBITRATION_OUTCOME_KEY = "arbitration_outcome"
ARBITRATION_RAW_KEY = "arbitration_raw"
ARBITRATION_RAW_MAX_LENGTH = 200
_CANDIDATE_SEPARATOR = ","


def _diagnostics(
    shortlist: ArbitrationShortlist,
    ambiguous_models: Sequence[str] = (),
    trace: Optional[ArbitrationTrace] = None,
) -> Dict[str, str]:
    diagnostics: Dict[str, str] = {}
    if shortlist.semantic_status is not None:
        diagnostics[SEMANTIC_STATUS_DIAGNOSTIC_KEY] = shortlist.semantic_status.value
    if ambiguous_models:
        diagnostics[AMBIGUOUS_CANDIDATES_KEY] = _CANDIDATE_SEPARATOR.join(ambiguous_models)
    if trace is not None:
        diagnostics[ARBITRATION_OUTCOME_KEY] = trace.status
        if trace.raw is not None:
            diagnostics[ARBITRATION_RAW_KEY] = trace.raw[:ARBITRATION_RAW_MAX_LENGTH]
    return diagnostics


def ambiguous_candidates_of(concept: ResolvedConcept) -> List[str]:
    """Tied fuzzy candidates an unresolved concept could not choose between."""
    published = concept.diagnostics.get(AMBIGUOUS_CANDIDATES_KEY, "")
    return [model for model in published.split(_CANDIDATE_SEPARATOR) if model]


def _resolve_strict_candidates(
    query_text: str,
    clean_query: str,
    G,
    llm,
    language: Optional[str],
    use_static_aliases: bool,
    fuzzy_results: List[Tuple[str, float]],
) -> ResolvedConcept:
    top_score = fuzzy_results[0][1]
    is_ambiguous = (
        len(fuzzy_results) >= 2
        and (fuzzy_results[0][1] - fuzzy_results[1][1]) < AMBIGUITY_GAP_THRESHOLD
    )
    if not is_ambiguous:
        return ResolvedConcept(
            user_term=query_text,
            resolved_models=[model for model, _score in fuzzy_results],
            confidence=round(top_score / 100, 2),
            source_step="fuzzy_graph_match",
            is_resolved=True,
            reason=f"Fuzzy matched graph labels: {_describe(fuzzy_results)}",
        )

    tiebreaker_winner = _deterministic_tiebreak(clean_query, fuzzy_results, G)
    if tiebreaker_winner:
        return ResolvedConcept(
            user_term=query_text,
            resolved_models=[tiebreaker_winner],
            confidence=round(top_score / 100, 2) * 0.9,
            source_step="fuzzy_tiebreak",
            is_resolved=True,
            reason=(
                f"Deterministic tiebreak among ambiguous fuzzy candidates "
                f"({_describe(fuzzy_results)}) "
                f"-> '{tiebreaker_winner}' (model/module name overlap in query)."
            ),
        )

    shortlist = build_arbitration_shortlist(
        clean_query, G, language, use_static_aliases, llm is not None,
    )
    trace = _llm_arbitrate(
        query_text,
        shortlist.models,
        llm,
        _candidate_contexts(G, shortlist.models, language),
    )
    chosen = trace.choice
    if chosen is not None:
        return ResolvedConcept(
            user_term=query_text,
            resolved_models=[chosen],
            confidence=0.6,
            source_step="llm_arbitration",
            is_resolved=True,
            reason=(
                f"LLM arbitration among ambiguous fuzzy candidates "
                f"({_describe(fuzzy_results)}) -> chose '{chosen}'. "
                f"Low-confidence LLM interpretation, not a certain structural fact."
            ),
            diagnostics=_diagnostics(shortlist, trace=trace),
        )

    return ResolvedConcept(
        user_term=query_text,
        is_resolved=False,
        confidence=0.0,
        source_step="unresolved",
        reason=(
            f"Ambiguous fuzzy candidates "
            f"({_describe(fuzzy_results)}) "
            f"and {_arbitration_outcome(llm)}."
        ),
        diagnostics=_diagnostics(shortlist, [model for model, _score in fuzzy_results], trace),
    )


def _resolve_widened_candidates(
    query_text: str,
    clean_query: str,
    G,
    llm,
    language: Optional[str],
    use_static_aliases: bool,
) -> Optional[ResolvedConcept]:
    widened_results = _fuzzy_match_graph(
        clean_query, G,
        threshold=WIDENED_CANDIDATE_THRESHOLD,
        limit=WIDENED_CANDIDATE_LIMIT,
        language=language,
        use_static_synonyms=use_static_aliases,
    )
    if not widened_results and llm is None:
        return None

    shortlist = build_arbitration_shortlist(
        clean_query, G, language, use_static_aliases, llm is not None, widened_results,
    )
    trace = (
        _llm_arbitrate(
            query_text,
            shortlist.models,
            llm,
            _candidate_contexts(G, shortlist.models, language),
        )
        if shortlist.models
        else None
    )
    chosen = trace.choice if trace is not None else None
    widened_description = _describe(widened_results) or "none"
    if chosen is not None:
        return ResolvedConcept(
            user_term=query_text,
            resolved_models=[chosen],
            confidence=0.5,
            source_step="llm_arbitration_widened",
            is_resolved=True,
            reason=(
                f"No candidate reached the strict fuzzy threshold; widened "
                f"low-threshold candidates "
                f"({widened_description}; "
                f"shortlist: {', '.join(shortlist.models)}) "
                f"-> LLM chose '{chosen}'. Low-confidence LLM interpretation "
                f"over a weak candidate shortlist, not a certain structural fact."
            ),
            diagnostics=_diagnostics(shortlist, trace=trace),
        )

    return ResolvedConcept(
        user_term=query_text,
        is_resolved=False,
        confidence=0.0,
        source_step="unresolved",
        reason=(
            f"No candidate reached the strict fuzzy threshold; widened candidates "
            f"({widened_description}; shortlist: {', '.join(shortlist.models) or 'none'}) "
            f"and {_arbitration_outcome(llm)}."
        ),
        diagnostics=_diagnostics(shortlist, trace=trace),
    )


def resolve_fuzzy_match(
    query_text: str,
    clean_query: str,
    G,
    llm,
    language: Optional[str],
    use_static_aliases: bool,
    semantic_candidates: Sequence[str] = (),
) -> Optional[ResolvedConcept]:
    """Resolve through fuzzy graph labels; None when there is nothing to arbitrate."""
    if G is None:
        return None
    fuzzy_results = _fuzzy_match_graph(
        clean_query,
        G,
        language=language,
        use_static_synonyms=use_static_aliases,
    )
    if fuzzy_results:
        if semantic_candidates and semantic_candidates[0] != fuzzy_results[0][0]:
            candidates = list(dict.fromkeys(
                [model for model, _score in fuzzy_results[:5]] + list(semantic_candidates[:5])
            ))
            trace = _llm_arbitrate(
                query_text, candidates, llm, _candidate_contexts(G, candidates, language),
            ) if llm is not None else None
            if trace is not None and trace.choice is not None:
                return ResolvedConcept(
                    user_term=query_text,
                    resolved_models=[trace.choice],
                    confidence=0.6,
                    source_step="hybrid_arbitration",
                    is_resolved=True,
                    reason=(
                        "Lexical and semantic retrieval ranked different leading models; "
                        f"closed-list arbitration selected '{trace.choice}'."
                    ),
                    diagnostics={
                        ARBITRATION_OUTCOME_KEY: trace.status,
                        **({ARBITRATION_RAW_KEY: trace.raw[:ARBITRATION_RAW_MAX_LENGTH]}
                           if trace.raw is not None else {}),
                    },
                )
            diagnostics = {
                AMBIGUOUS_CANDIDATES_KEY: _CANDIDATE_SEPARATOR.join(candidates),
                ARBITRATION_OUTCOME_KEY: trace.status if trace is not None else "no_llm",
            }
            if trace is not None and trace.raw is not None:
                diagnostics[ARBITRATION_RAW_KEY] = trace.raw[:ARBITRATION_RAW_MAX_LENGTH]
            return ResolvedConcept(
                user_term=query_text,
                is_resolved=False,
                confidence=0.0,
                source_step="unresolved",
                reason="Lexical and semantic retrieval disagree; no candidate was safely selected.",
                diagnostics=diagnostics,
            )
        return _resolve_strict_candidates(
            query_text, clean_query, G, llm, language, use_static_aliases, fuzzy_results,
        )
    return _resolve_widened_candidates(
        query_text, clean_query, G, llm, language, use_static_aliases,
    )
