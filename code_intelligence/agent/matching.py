"""
code_intelligence/business_resolver_matching.py

Exact technical mentions, specificity ranking, and fuzzy graph matching
for resolving natural language concepts to Odoo models.
"""

import logging
import unicodedata
import weakref
from collections import defaultdict
import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Set

from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)


@dataclass
class ResolvedConcept:
    user_term: str
    resolved_models: List[str] = field(default_factory=list)
    resolved_modules: List[str] = field(default_factory=list)
    confidence: float = 1.0
    source_step: str = "unresolved"
    is_resolved: bool = True
    reason: str = ""
    diagnostics: Dict[str, str] = field(default_factory=dict)


# Cache indexe directement sur l'objet graphe (pas sur id(G)) : un
# WeakKeyDictionary retire automatiquement son entree des qu'un graphe est
# garbage-collecte (callback synchrone), ce qui elimine tout risque de
# collision d'id() reutilise entre deux objets-graphe differents et de
# duree de vie courte (bug reel observe et reproduit, todo/contexte.txt
# Section 721 -- avec Dict[int, ...] indexe par id(G), un graphe A detruit
# puis un graphe B different alloue a la meme adresse memoire faisait
# retourner silencieusement l'index fuzzy de A pour B).
_FUZZY_INDEX_CACHE: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _business_tokens(value: str) -> List[str]:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return [token for token in re.findall(r"[^\W_]+", normalized) if len(token) > 1]


def _business_text(value: str) -> str:
    return " ".join(_business_tokens(value))


def _paired_exact_field_model_matches(query: str, G) -> List[str]:
    """Find models named in the query through both a rare field and a rare label."""
    def normalize(value: str) -> str:
        decomposed = unicodedata.normalize("NFKD", value.casefold())
        return "".join(char for char in decomposed if not unicodedata.combining(char))

    def words(value: str) -> Set[str]:
        return set(re.findall(r"[^\W_]+", normalize(value), flags=re.UNICODE))

    graph_cache = _FUZZY_INDEX_CACHE.setdefault(G, {})
    cache_key = "paired_field_model"
    evidence_index = graph_cache.get(cache_key)
    if evidence_index is None:
        model_labels: Dict[str, Set[str]] = defaultdict(set)
        field_models: Dict[str, Set[str]] = defaultdict(set)
        label_models: Dict[str, Set[str]] = defaultdict(set)
        for _node_id, data in G.nodes(data=True):
            node_type = data.get("node_type")
            if node_type == "Model":
                model = data.get("name", "")
                if not model:
                    continue
                model_labels[model].update(words(data.get("description", "")))
                model_labels[model].update(words(model.replace(".", " ").replace("_", " ")))
                for label in data.get("business_labels", []):
                    model_labels[model].update(words(label.get("label", "")))
            elif node_type == "Field":
                name = data.get("name", "")
                model = data.get("model", "")
                if name and model:
                    field_models[name.casefold()].add(model)

        model_count = max(len(model_labels), 1)
        for model, labels in model_labels.items():
            for token in labels:
                label_models[token].add(model)
        max_owners = max(3, int(model_count * 0.02))
        evidence_index = (model_labels, field_models, label_models, max_owners)
        graph_cache[cache_key] = evidence_index

    model_labels, field_models, label_models, max_owners = evidence_index
    query_normalized = normalize(query)
    query_words = words(query)

    matching_fields = set()
    for field_name, owners in field_models.items():
        normalized_name = normalize(field_name)
        explicit_identifier = "_" in field_name or any(char.isdigit() for char in field_name)
        quoted_identifier = re.search(
            r"(['\"`])\s*" + re.escape(normalized_name) + r"\s*\1",
            query_normalized,
        )
        exact_mention = re.search(
            r"(?<!\w)" + re.escape(normalized_name) + r"(?!\w)", query_normalized,
        )
        if len(owners) <= max_owners and exact_mention and (explicit_identifier or quoted_identifier):
            matching_fields.update(owners)

    matching_label_models = set()
    for model, labels in model_labels.items():
        if any(
            token in query_words
            and len(label_models[token]) <= max_owners
            for token in labels
        ):
            matching_label_models.add(model)

    return sorted(matching_fields & matching_label_models)


def _build_fuzzy_index(G) -> List[Tuple[str, str]]:
    """Build (label, technical_model_name) pairs from graph nodes, with the labels of every graph language."""
    graph_cache = _FUZZY_INDEX_CACHE.setdefault(G, {})
    if "fuzzy_index" in graph_cache:
        return graph_cache["fuzzy_index"]

    index: List[Tuple[str, str]] = []

    for node_id, data in G.nodes(data=True):
        node_type = data.get("node_type")

        if node_type == "Model":
            model_name = data.get("name", node_id.replace("model:", ""))
            desc = data.get("description", "")
            if desc and len(desc) >= 3:
                index.append((desc.lower(), model_name))

        elif node_type == "Field":
            label = data.get("label", "")
            model_name = data.get("model", "")
            # Skip short generic field labels (e.g. "Date", "Nom").
            if label and model_name and len(label) >= 3 and (
                len(label.split()) >= 2 or len(label) >= 8
            ):
                index.append((label.lower(), model_name))

        elif node_type == "Menu":
            menu_name = data.get("name", "")
            if menu_name and len(menu_name) >= 3:
                for successor in G.successors(node_id):
                    edge_data = G.edges[node_id, successor]
                    if edge_data.get("edge_type") == "OPENS_MODEL":
                        model_name = successor.replace("model:", "")
                        index.append((menu_name.lower(), model_name))
                        break

        if node_type == "Model":
            technical_name = data.get("name", node_id.replace("model:", ""))
            if technical_name:
                index.append((technical_name.lower(), technical_name))
                spaced = technical_name.replace(".", " ").replace("_", " ")
                if spaced != technical_name:
                    index.append((spaced.lower(), technical_name))

        if node_type in {"Model", "Field", "Menu"}:
            for translation in data.get("business_labels", []):
                label = translation.get("label", "").strip()
                if not label or len(label) < 3:
                    continue
                if node_type == "Model":
                    model_name = data.get("name", node_id.replace("model:", ""))
                elif node_type == "Field":
                    model_name = data.get("model", "")
                else:
                    model_name = next((
                        successor.replace("model:", "")
                        for successor in G.successors(node_id)
                        if G.edges[node_id, successor].get("edge_type") == "OPENS_MODEL"
                    ), "")
                if model_name:
                    index.append((label.lower(), model_name))

    module_labels = defaultdict(set)
    for node_id, data in G.nodes(data=True):
        if data.get("node_type") != "Menu" or not data.get("module"):
            continue
        is_root = not any(
            G.edges[node_id, successor].get("edge_type") == "CHILD_OF"
            for successor in G.successors(node_id)
        )
        if not is_root:
            continue
        for translation in data.get("business_labels", []):
            label = translation.get("label", "").strip()
            if not label or len(label) < 3:
                continue
            module_labels[data["module"]].add(label.lower())

    for node_id, data in G.nodes(data=True):
        if data.get("node_type") != "Model":
            continue
        model_name = data.get("name", node_id.replace("model:", ""))
        labels = [data.get("description", "")]
        labels.extend(translation.get("label", "") for translation in data.get("business_labels", []))
        modules = [
            successor.removeprefix("module:")
            for successor in G.successors(node_id)
            if G.edges[node_id, successor].get("edge_type") == "DEFINED_IN"
            and G.edges[node_id, successor].get("role", "declares") == "declares"
        ]
        for module in modules:
            for model_label in labels:
                model_label = model_label.strip().lower()
                if not model_label:
                    continue
                for module_label in module_labels.get(module, ()):
                    index.append((f"{model_label} {module_label}", model_name))

    graph_cache["fuzzy_index"] = index
    logger.info("Built fuzzy index: %d entries from graph (%d nodes)", len(index), G.number_of_nodes())
    return index


_GENERIC_FIELD_NAMES = {
    "name", "state", "active", "sequence", "create_uid", "create_date",
    "write_uid", "write_date", "company_id", "currency_id", "description",
    "note", "user_id", "partner_id", "date", "type", "id", "display_name",
    "color", "product_id", "product_uom_id", "categ_id", "parent_id",
    "message_ids", "activity_ids", "message_follower_ids",
}


def _find_exact_technical_model_mentions(
    query_lower: str, G, *, include_symbol_inference: bool = True
) -> List[str]:
    """Find exact technical Odoo model names mentioned in query.

    The method/button fallback is useful when a question contains only a
    technical symbol such as ``action_confirm``.  It is not an exact model
    mention, however: several unrelated models can expose the same method
    name, so callers can disable it with ``include_symbol_inference=False``.
    """
    if G is None:
        return []
    found = []
    for node_id, data in G.nodes(data=True):
        if data.get("node_type") != "Model":
            continue
        technical_name = data.get("name", node_id.replace("model:", ""))
        if not technical_name or len(technical_name) < 3:
            continue
        # Section 890 (todo/contexte.txt): a plain word-boundary lookahead
        # ("." is not \w) lets a model whose technical name collides with a
        # module prefix -- 'base' is the classic case -- match inside an
        # unrelated dotted token like a group xml_id ("base.group_portal")
        # in the question text. (?!\.\w) additionally requires that the
        # match not be followed by "." + a word char, i.e. not be merely the
        # first component of a LONGER dotted identifier (an xml_id, or a
        # more specific model name such as 'sale.order.line' vs 'sale.order').
        # A genuine full dotted model name (e.g. 'sale.order') is unaffected:
        # its own technical_name already includes the dots, so the pattern
        # is anchored on the complete name, not a prefix of it.
        pattern = r"(?<!\w)" + re.escape(technical_name.lower()) + r"(?!\w)(?!\.\w)"
        if technical_name.isalpha():
            # A one-word name ('base') is also an ordinary word: require "model <name>".
            pattern = r"(?<!\w)(?:mod[\u00e8e]le|model)\s+['\"`]?" + re.escape(technical_name.lower()) + r"(?!\w)(?!\.\w)"
        if re.search(pattern, query_lower):
            found.append(technical_name)
    if not found and include_symbol_inference:
        field_models: Dict[str, Set[str]] = {}
        for node_id, data in G.nodes(data=True):
            nt = data.get("node_type")
            if nt in {"Method", "Button", "Menu"}:
                candidates = []
                m_name = (data.get("name") or "").strip().lower()
                if len(m_name) >= 6 and (m_name.startswith(("action_", "button_", "_compute_", "_check_")) or "_" in m_name):
                    candidates.append(m_name)
                m_label = (data.get("label") or "").strip().lower()
                if len(m_label) >= 4 and " " in m_label:
                    candidates.append(m_label)
                for cand in candidates:
                    pattern = r"(?<!\w)" + re.escape(cand) + r"(?!\w)"
                    if re.search(pattern, query_lower):
                        parent_model = data.get("model")
                        if parent_model and parent_model not in found:
                            found.append(parent_model)
            elif nt == "Field":
                f_name = (data.get("name") or "").strip().lower()
                if f_name and f_name not in _GENERIC_FIELD_NAMES and len(f_name) >= 5 and ("_" in f_name or f_name.startswith("x_")):
                    parent_model = data.get("model")
                    if parent_model:
                        field_models.setdefault(f_name, set()).add(parent_model)
        if not found and field_models:
            for f_name, models in field_models.items():
                if len(models) <= 3:
                    pattern = r"(?<!\w)" + re.escape(f_name) + r"(?!\w)"
                    if re.search(pattern, query_lower):
                        for m in models:
                            if m not in found:
                                found.append(m)
    return found


def has_non_generic_field_mention(query_lower: str, G) -> bool:
    """Return whether the question names a specific indexed field."""
    if G is None:
        return False
    for _node_id, data in G.nodes(data=True):
        if data.get("node_type") != "Field":
            continue
        field_name = (data.get("name") or "").strip().lower()
        if field_name in _GENERIC_FIELD_NAMES or len(field_name) < 5:
            continue
        if re.search(r"(?<!\w)" + re.escape(field_name) + r"(?!\w)", query_lower):
            return True
    return False


def _find_exact_technical_module_mentions(query_lower: str, G) -> List[str]:
    """Find exact technical Odoo module names mentioned in query."""
    if G is None:
        return []
    found = []
    for node_id, data in G.nodes(data=True):
        if data.get("node_type") != "Module" and not node_id.startswith("module:"):
            continue
        mod_name = data.get("name", node_id.replace("module:", ""))
        if not mod_name or len(mod_name) < 3:
            continue
        mod_lower = mod_name.lower()
        mod_escaped = re.escape(mod_lower).replace('_', r'[\s_]+')
        marked = r"(?<!\w)(?:module|addon)\s+" + mod_escaped + r"(?!\w)(?!\.\w)"
        # Only a name written with "_" is unmistakably technical; a plain word needs "module <name>".
        literal = r"(?<!\w)" + re.escape(mod_lower) + r"(?!\w)(?!\.\w)"
        if re.search(marked, query_lower) or ("_" in mod_lower and re.search(literal, query_lower)):
            if mod_name not in found:
                found.append(mod_name)

    return found


def _specificity_score(technical_name: str, query_lower: str) -> Tuple[int, int, int, int, int, int, int]:
    """Deterministic specificity score for an exact technical model mention."""
    is_explicit = 1 if re.search(r"\b(?:mod[èe]le|model)\s+['\"]?" + re.escape(technical_name.lower()) + r"['\"]?\b", query_lower) else 0

    has_context_mention = 0
    for part in technical_name.split("."):
        if len(part) >= 4 and re.search(r"(?<!\w)" + re.escape(part.lower()) + r"(?!\w)", query_lower):
            has_context_mention = 1
            break

    is_domain_model = 0 if (
        technical_name.startswith("ir.")
        or technical_name == "base"
        or technical_name.endswith(".settings")
        or "config.settings" in technical_name
    ) else 1
    segments = technical_name.count(".") + 1
    length = len(technical_name)
    is_custom = 1 if technical_name.startswith(("custom.", "x_")) else 0
    pattern = r"(?<!\w)" + re.escape(technical_name.lower()) + r"(?!\w)"
    occurrences = len(re.findall(pattern, query_lower))
    return (is_explicit, has_context_mention, is_domain_model, segments, length, is_custom, occurrences)


def rank_by_specificity(matches: List[str], query_lower: str) -> List[str]:
    """Arbitrate between several exact technical model mentions found verbatim."""
    if len(matches) <= 1:
        return matches
    scored = [(m, _specificity_score(m, query_lower)) for m in matches]
    # Exact technical mentions are independent targets when the user names
    # more than one model. Specificity orders dispatch; it must not discard a
    # co-mentioned model (STK-Q1: stock.quant + stock.move.line).
    return [m for m, _score in sorted(scored, key=lambda item: item[1], reverse=True)]


def _dotted_technical_name_only_embedded(technical_name: str, raw_query_lower: str) -> bool:
    """Section 1064 (fuzzy-matching counterpart to the Section 890 guard):
    True when a dotted technical model name appears in the raw query ONLY
    as the prefix of a strictly longer dotted identifier, never as a
    standalone mention of itself -- e.g. 'custom.deep.document' inside
    'other.custom.deep.document.extended'. Section 890 closed this for the
    exact-technical-mention step (_find_exact_technical_model_mentions)
    via the same (?!\\.\\w) lookahead, but _fuzzy_match_graph indexes each
    model's own technical name as a label for itself (_build_fuzzy_index)
    and scores it with rapidfuzz's token-set comparison, which is
    dot-insensitive by construction (_business_text strips all
    punctuation before scoring) and so cannot see this distinction at all
    -- the two checks were never actually the same code path, despite
    looking like they covered the same bug.
    """
    if "." not in technical_name:
        return False
    standalone_pattern = r"(?<!\w)" + re.escape(technical_name) + r"(?!\w)(?!\.\w)"
    if re.search(standalone_pattern, raw_query_lower):
        return False
    embedded_pattern = r"(?<!\w)" + re.escape(technical_name) + r"\.\w"
    return bool(re.search(embedded_pattern, raw_query_lower))


def _fuzzy_match_graph(
    query: str,
    G,
    threshold: int = 75,
    limit: int = 5,
) -> List[Tuple[str, float]]:
    """Fuzzy match query against indexed graph node labels and models."""
    index = _build_fuzzy_index(G)
    if not index:
        return []

    paired_matches = _paired_exact_field_model_matches(query, G)
    if paired_matches:
        return [(model, 100.0) for model in paired_matches[:limit]]

    labels = [_business_text(entry[0]) for entry in index]
    query_lower = _business_text(query)
    query_token_count = max(len(_business_tokens(query)), 1)
    raw_query_lower = query.lower()
    # Section 1064: which index rows are a model's OWN technical-name
    # self-entry (plain dotted, or the "."/"_" -> " " spaced variant) --
    # both added by _build_fuzzy_index right after the technical_name
    # check. Only these rows can trigger the embedded-substring false
    # positive above; a genuine prose description/field/menu label never
    # equals the bare technical name, so it is never affected.
    self_entry_technical_names = [
        model if (label == model.lower() or label == model.lower().replace(".", " ").replace("_", " ")) else None
        for label, model in index
    ]

    model_scores: Dict[str, float] = {}

    for scorer in (fuzz.token_set_ratio, fuzz.token_sort_ratio):
        hits = process.extract(
            query_lower, labels,
            scorer=scorer,
            score_cutoff=threshold * 0.6,
            limit=limit * 5,
        )
        for _text, score, idx in (hits or []):
            label = index[idx][0]
            self_technical_name = self_entry_technical_names[idx]
            if self_technical_name and _dotted_technical_name_only_embedded(self_technical_name, raw_query_lower):
                continue
            label_token_count = max(len(_business_tokens(label)), 1)
            length_penalty = min(label_token_count / query_token_count, 1.0) ** 0.5
            adjusted = score * length_penalty
            if adjusted >= threshold:
                model = index[idx][1]
                model_scores[model] = max(model_scores.get(model, 0.0), adjusted)

    query_tokens = _business_tokens(query)
    if len(query_tokens) > 1:
        max_window = min(6, len(query_tokens))
        # Min width 2: single-token windows cause mass ties on generic labels.
        windows = {
            " ".join(query_tokens[start:start + width])
            for width in range(2, max_window + 1)
            for start in range(len(query_tokens) - width + 1)
        }
        for window in windows:
            window_words = window.split()
            window_token_count = len(window_words)
            hits = process.extract(
                window,
                labels,
                scorer=fuzz.token_set_ratio,
                score_cutoff=threshold * 0.65,
                limit=limit * 8,
            )
            for _text, score, idx in hits or []:
                label = index[idx][0]
                self_technical_name = self_entry_technical_names[idx]
                if self_technical_name and _dotted_technical_name_only_embedded(self_technical_name, raw_query_lower):
                    continue
                label_words = _business_tokens(label)
                matched_words = sum(
                    any(fuzz.ratio(word, label_word) >= 85 for label_word in label_words)
                    for word in window_words
                )
                if matched_words / window_token_count < 0.66:
                    continue
                label_token_count = max(len(label_words), 1)
                length_ratio = min(window_token_count, label_token_count) / max(window_token_count, label_token_count)
                adjusted = score * length_ratio ** 0.25
                if adjusted >= threshold:
                    model = index[idx][1]
                    model_scores[model] = max(model_scores.get(model, 0.0), adjusted)

    sorted_results = sorted(model_scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_results[:limit]
