"""Evidence step: multi-word instance labels of models quoted verbatim in the question."""

import re
import unicodedata
from collections import defaultdict
from typing import Dict, Set

from ..matching import _FUZZY_INDEX_CACHE, _paired_exact_field_model_matches

MIN_LABEL_WORDS = 2
_WORD = re.compile(r"\w+")
_CACHE_KEY = "multiword_model_labels"


def _fold(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def _model_labels(G) -> Dict[str, Set[str]]:
    graph_cache = _FUZZY_INDEX_CACHE.setdefault(G, {})
    if _CACHE_KEY not in graph_cache:
        labels = defaultdict(set)
        for node_id, data in G.nodes(data=True):
            if data.get("node_type") != "Model":
                continue
            model = data.get("name", node_id.removeprefix("model:"))
            for entry in data.get("business_labels", []):
                label = _fold(str(entry.get("label") or "").strip())
                if len(_WORD.findall(label)) >= MIN_LABEL_WORDS:
                    labels[label].add(model)
        graph_cache[_CACHE_KEY] = dict(labels)
    return graph_cache[_CACHE_KEY]


def _maximal_labels(query: str, labels) -> Set[str]:
    """Labels found as whole words, without those contained in a longer label found in the query."""
    spans = [
        (match.start(), match.end(), label)
        for label in labels
        for match in re.finditer(r"(?<!\w)" + re.escape(label) + r"(?!\w)", query)
    ]
    return {
        label for start, end, label in spans
        if not any(o_start <= start and end <= o_end and o_end - o_start > end - start for o_start, o_end, _ in spans)
    }


def quoted_model_labels(clean_query: str, G) -> Dict[str, str]:
    """Models owning a multi-word instance label quoted verbatim in the question, with that label.

    A quoted label proves a model is mentioned, not that it is the only subject: it is evidence for
    the arbiter, never a decision. A field-and-label pair pointing at a model is stronger evidence
    of the subject than a label that may only complement it, so the labels are then ignored.
    """
    if G is None:
        return {}
    labels = _model_labels(G)
    found = _maximal_labels(_fold(clean_query), labels)
    if not found or _paired_exact_field_model_matches(clean_query, G):
        return {}
    return {model: label for label in sorted(found) for model in sorted(labels[label])}
