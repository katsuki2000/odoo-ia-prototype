"""Select targets from one bounded lexical/semantic candidate set."""

from typing import List
from .matching import ResolvedConcept, _fuzzy_match_graph
from .arbitration import QUOTED_LABEL_MARKER, _llm_arbitrate
from .candidates import (
    HYBRID_SEMANTIC_LIMIT, SHORTLIST_FUZZY_LIMIT, WIDENED_CANDIDATE_THRESHOLD,
    WIDENED_CANDIDATE_LIMIT, _candidate_contexts,
)

AMBIGUOUS_CANDIDATES_KEY = 'ambiguous_candidates'
ARBITRATION_OUTCOME_KEY = 'arbitration_outcome'
ARBITRATION_RAW_KEY = 'arbitration_raw'
ARBITRATION_RAW_MAX_LENGTH = 200


def ambiguous_candidates_of(concept: ResolvedConcept) -> List[str]:
    return [model for model in concept.diagnostics.get(AMBIGUOUS_CANDIDATES_KEY, '').split(',') if model]


def resolve_fuzzy_match(query_text, clean_query, G, llm, language, semantic_candidates=(), quoted_labels=None):
    quoted_labels = quoted_labels or {}
    if G is None:
        return None
    lexical = _fuzzy_match_graph(clean_query, G)
    strict = bool(lexical)
    if not lexical:
        lexical = _fuzzy_match_graph(clean_query, G, threshold=WIDENED_CANDIDATE_THRESHOLD,
                                     limit=WIDENED_CANDIDATE_LIMIT)
    candidates = list(dict.fromkeys(list(quoted_labels) + [model for model, _score in lexical[:SHORTLIST_FUZZY_LIMIT]]
                                   + list(semantic_candidates[:HYBRID_SEMANTIC_LIMIT])))
    candidates = [model for model in candidates if G.has_node('model:' + model)
                  and G.nodes['model:' + model].get('node_type') == 'Model']
    if not candidates:
        return None
    if strict and len(candidates) == 1:
        return ResolvedConcept(user_term=query_text, resolved_models=candidates,
                               confidence=round(lexical[0][1] / 100, 2), source_step='fuzzy_graph_match',
                               is_resolved=True, reason='One strict graph-label candidate; no competing retrieved model.')
    contexts = _candidate_contexts(G, candidates)
    for model, label in quoted_labels.items():
        contexts[model] = '; '.join(filter(None, [f"{QUOTED_LABEL_MARKER}: {label}", contexts.get(model)]))
    trace = _llm_arbitrate(query_text, candidates, llm, contexts)
    diagnostics = {ARBITRATION_OUTCOME_KEY: trace.status,
                   'arbitration_attempts': str(trace.attempts), 'arbitration_wait_seconds': str(trace.waitSeconds)}
    if trace.raw is not None:
        diagnostics[ARBITRATION_RAW_KEY] = trace.raw[:ARBITRATION_RAW_MAX_LENGTH]
    choices = list(trace.choices or ((trace.choice,) if trace.choice else ()))
    if choices:
        return ResolvedConcept(user_term=query_text, resolved_models=choices, confidence=0.6 if strict else 0.5,
                               source_step='hybrid_arbitration' if semantic_candidates else 'llm_arbitration',
                               is_resolved=True, reason='Bounded arbitration selected explicit targets from retrieved candidates.',
                               diagnostics=diagnostics)
    diagnostics[AMBIGUOUS_CANDIDATES_KEY] = ','.join(candidates)
    return ResolvedConcept(user_term=query_text, is_resolved=False, confidence=0.0, source_step='unresolved',
                           reason='Candidates remain alternatives; no safe target selection.', diagnostics=diagnostics)
