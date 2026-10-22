"""Arbitration shortlist assembly and deterministic tie-breaking for the business resolver."""

import logging
import weakref
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from .matching import _fuzzy_match_graph
from .semantic_retrieval import SemanticRetrievalStatus, retrieve_semantic_model_candidates

_logger = logging.getLogger(__name__)

_TIEBREAK_RARITY_CACHE: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()

AMBIGUITY_GAP_THRESHOLD = 10.0
WIDENED_CANDIDATE_THRESHOLD = 30
WIDENED_CANDIDATE_LIMIT = 20
SHORTLIST_SEMANTIC_LIMIT = 20
SHORTLIST_FUZZY_LIMIT = 5
# Semantic share of the closed list when lexical and semantic leaders disagree (or lexical is empty).
HYBRID_SEMANTIC_LIMIT = 20

# Avoid generic 2-3 char words matching inside dotted model names.
_MIN_SEGMENT_LEN = 4


def _candidate_contexts(G, candidates: List[str]) -> Dict[str, str]:
    """Describe candidates with labels in every graph language and declaring modules."""
    contexts = {}
    for model in candidates:
        node_id = f"model:{model}"
        if not G.has_node(node_id):
            continue
        data = G.nodes[node_id]
        labels = []
        for label in data.get("business_labels", []):
            label_text = str(label.get("label") or "").strip()
            if not label_text:
                continue
            if label_text not in labels:
                labels.append(label_text)
        description = str(data.get("description") or "").strip()
        if description and description not in labels:
            labels.append(description)
        modules = sorted({
            successor.removeprefix("module:")
            for successor in G.successors(node_id)
            if G.edges[node_id, successor].get("edge_type") == "DEFINED_IN"
            and G.edges[node_id, successor].get("role", "declares") == "declares"
        })
        details = []
        if labels:
            details.append(f"labels: {', '.join(labels[:3])}")
        if modules:
            details.append(f"modules: {', '.join(modules)}")
        if details:
            contexts[model] = "; ".join(details)
    return contexts


@dataclass(frozen=True)
class ArbitrationShortlist:
    models: List[str]
    semantic_status: Optional[SemanticRetrievalStatus] = None


def build_arbitration_shortlist(
    query: str,
    G,
    language: Optional[str],
    use_semantic_retrieval: bool,
    fuzzy_results: Optional[List[Tuple[str, float]]] = None,
) -> ArbitrationShortlist:
    """Combine deterministic and optional semantic candidates for arbitration."""
    if fuzzy_results is None:
        fuzzy_results = _fuzzy_match_graph(query, G, limit=WIDENED_CANDIDATE_LIMIT)
    fuzzy_models = [model for model, _score in fuzzy_results]
    retrieval = (
        retrieve_semantic_model_candidates(query, G, language, limit=SHORTLIST_SEMANTIC_LIMIT)
        if use_semantic_retrieval else None
    )
    semantic_status = retrieval.status if retrieval else None
    semantic_models = retrieval.models if retrieval else []
    if not semantic_models:
        return ArbitrationShortlist(fuzzy_models, semantic_status)

    candidates = list(dict.fromkeys(fuzzy_models[:SHORTLIST_FUZZY_LIMIT] + semantic_models))
    return ArbitrationShortlist(candidates, semantic_status)


def _arbitration_candidates(
    query: str,
    G,
    language: Optional[str],
    use_semantic_retrieval: bool,
    fuzzy_results: Optional[List[Tuple[str, float]]] = None,
) -> List[str]:
    return build_arbitration_shortlist(query, G, language, use_semantic_retrieval, fuzzy_results).models


def _tiebreak_rarity_index(G) -> Tuple[Dict[str, int], Dict[str, int], int]:
    """Count how many DISTINCT models share each dotted-name segment and how many models each
    declaring module owns, cached per graph. Built over every Model node (not just the tied
    candidates), with the same "rare token" discipline as matching.py
    (_paired_exact_field_model_matches, max_owners = max(3, 2% of models)).
    Without it, _deterministic_tiebreak would reward ANY shared segment equally: on a
    535-model graph 'line' names 21 models and 'order' names 10, generic words that do not
    discriminate.
    """
    cached = _TIEBREAK_RARITY_CACHE.get(G)
    if cached is not None:
        return cached

    segment_owners: Dict[str, Set[str]] = {}
    module_owners: Dict[str, Set[str]] = {}
    model_count = 0
    for node_id, data in G.nodes(data=True):
        if data.get("node_type") != "Model":
            continue
        model = data.get("name", "")
        if not model:
            continue
        model_count += 1
        for seg in model.lower().replace("_", " ").split("."):
            if len(seg) < _MIN_SEGMENT_LEN:
                continue
            segment_owners.setdefault(seg, set()).add(model)
        for successor in G.successors(node_id):
            edge = G.edges[node_id, successor]
            if edge.get("edge_type") == "DEFINED_IN" and edge.get("role", "declares") == "declares":
                mod_name = successor.removeprefix("module:").lower()
                if len(mod_name) >= _MIN_SEGMENT_LEN:
                    module_owners.setdefault(mod_name, set()).add(model)

    max_owners = max(3, int(model_count * 0.02))
    segment_counts = {seg: len(owners) for seg, owners in segment_owners.items()}
    module_counts = {mod: len(owners) for mod, owners in module_owners.items()}
    result = (segment_counts, module_counts, max_owners)
    _TIEBREAK_RARITY_CACHE[G] = result
    return result


def _deterministic_tiebreak(
    query_lower: str,
    fuzzy_results: List[Tuple[str, float]],
    G,
) -> Optional[str]:
    """Break a fuzzy tie only on a unique model or declaring-module mention,
    and only when that mention is RARE across the graph's own model names: a segment or
    module shared by many models does not discriminate, however literally it appears in the query."""
    import re as _re

    top_score = fuzzy_results[0][1]
    tied = [m for m, s in fuzzy_results if (top_score - s) < AMBIGUITY_GAP_THRESHOLD]
    if len(tied) < 2:
        return None

    context_query = _re.sub(r"(?<!\w)[\w]+(?:\.[\w]+)+(?!\w)", " ", query_lower)
    context_query = _re.sub(r"(?<!\w)group_[\w]+(?!\w)", " ", context_query)

    segment_counts, module_counts, max_owners = _tiebreak_rarity_index(G)
    scores: Dict[str, int] = {m: 0 for m in tied}

    for model in tied:
        segments = model.lower().replace("_", " ").split(".")
        for seg in segments:
            if len(seg) < _MIN_SEGMENT_LEN or segment_counts.get(seg, 0) > max_owners:
                continue
            for variant in (seg, seg.replace(" ", "_")):
                pattern = r"(?<![\w.])" + _re.escape(variant) + r"(?![\w.])"
                if _re.search(pattern, context_query):
                    scores[model] += 2
                    break

        model_node = f"model:{model}"
        if G.has_node(model_node):
            for successor in G.successors(model_node):
                edge = G.edges[model_node, successor]
                if (
                    edge.get("edge_type") == "DEFINED_IN"
                    and edge.get("role", "declares") == "declares"
                ):
                    mod_name = successor.removeprefix("module:").lower()
                    if len(mod_name) < _MIN_SEGMENT_LEN or module_counts.get(mod_name, 0) > max_owners:
                        continue
                    mod_pattern = r"(?<![\w.])" + _re.escape(mod_name) + r"(?![\w.])"
                    if _re.search(mod_pattern, context_query):
                        scores[model] += 3

    # Only return a winner if exactly one candidate has the highest score AND it's > 0
    max_score = max(scores.values())
    if max_score <= 0:
        return None
    winners = [m for m, s in scores.items() if s == max_score]
    if len(winners) == 1:
        _logger.info(
            "Tiebreak resolved: %s (score %d) from %d tied candidates",
            winners[0], max_score, len(tied),
        )
        return winners[0]
    return None


__all__ = [
    "AMBIGUITY_GAP_THRESHOLD",
    "WIDENED_CANDIDATE_THRESHOLD",
    "WIDENED_CANDIDATE_LIMIT",
    "SHORTLIST_SEMANTIC_LIMIT",
    "SHORTLIST_FUZZY_LIMIT",
    "HYBRID_SEMANTIC_LIMIT",
    "ArbitrationShortlist",
    "build_arbitration_shortlist",
    "_arbitration_candidates",
    "_candidate_contexts",
    "_deterministic_tiebreak",
]
