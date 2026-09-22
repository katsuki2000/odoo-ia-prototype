"""
code_intelligence/business_resolver_matching.py

Exact technical mentions, specificity ranking, and fuzzy graph matching
for resolving natural language concepts to Odoo models.
"""

import logging
import weakref
from pathlib import Path
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Set

from rapidfuzz import fuzz, process

from .aliases import (
    BUSINESS_ALIASES_NFC,
    _ALIAS_PATTERNS,
    NATIVE_MODEL_SYNONYMS,
)

logger = logging.getLogger(__name__)


@dataclass
class ResolvedConcept:
    user_term: str
    resolved_models: List[str] = field(default_factory=list)
    resolved_modules: List[str] = field(default_factory=list)
    confidence: float = 1.0
    source_step: str = "static_alias"
    is_resolved: bool = True
    reason: str = ""


# Cache indexe directement sur l'objet graphe (pas sur id(G)) : un
# WeakKeyDictionary retire automatiquement son entree des qu'un graphe est
# garbage-collecte (callback synchrone), ce qui elimine tout risque de
# collision d'id() reutilise entre deux objets-graphe differents et de
# duree de vie courte (bug reel observe et reproduit, todo/contexte.txt
# Section 721 -- avec Dict[int, ...] indexe par id(G), un graphe A detruit
# puis un graphe B different alloue a la meme adresse memoire faisait
# retourner silencieusement l'index fuzzy de A pour B).
_FUZZY_INDEX_CACHE: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _build_fuzzy_index(G) -> List[Tuple[str, str]]:
    """Build (label, technical_model_name) pairs from graph nodes for fuzzy matching."""
    if G in _FUZZY_INDEX_CACHE:
        return _FUZZY_INDEX_CACHE[G]

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
            if label and model_name and len(label) >= 3:
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

    for model_name, synonyms in NATIVE_MODEL_SYNONYMS.items():
        if not G.has_node(f"model:{model_name}"):
            continue
        for synonym in synonyms:
            index.append((synonym.lower(), model_name))

    _FUZZY_INDEX_CACHE[G] = index
    logger.info("Built fuzzy index: %d entries from graph (%d nodes)", len(index), G.number_of_nodes())
    return index


_GENERIC_FIELD_NAMES = {
    "name", "state", "active", "sequence", "create_uid", "create_date",
    "write_uid", "write_date", "company_id", "currency_id", "description",
    "note", "user_id", "partner_id", "date", "type", "id", "display_name",
    "color", "product_id", "product_uom_id", "categ_id", "parent_id",
    "message_ids", "activity_ids", "message_follower_ids",
}


def _find_exact_technical_model_mentions(query_lower: str, G) -> List[str]:
    """Find exact technical Odoo model names mentioned in query."""
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
        if re.search(pattern, query_lower):
            found.append(technical_name)
    if not found:
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


def _find_exact_technical_module_mentions(query_lower: str, G) -> List[str]:
    """Find exact technical Odoo module names mentioned in query."""
    if G is None:
        return []
    found = []
    generic_module_words = {"base", "mail", "web", "auth", "sale", "account", "stock", "purchase", "point_of_sale"}
    for node_id, data in G.nodes(data=True):
        if data.get("node_type") != "Module" and not node_id.startswith("module:"):
            continue
        mod_name = data.get("name", node_id.replace("module:", ""))
        if not mod_name or len(mod_name) < 3:
            continue
        mod_lower = mod_name.lower()
        mod_escaped = re.escape(mod_lower).replace('_', r'[\s_]+')
        if mod_lower in generic_module_words:
            pattern = r"(?<!\w)(?:module|addon)\s+" + mod_escaped + r"(?!\w)"
        else:
            pattern = r"(?<!\w)" + mod_escaped + r"(?!\w)"
        if re.search(pattern, query_lower):
            if mod_name not in found:
                found.append(mod_name)

    if not found:
        for node_id, data in G.nodes(data=True):
            nt = data.get("node_type")
            if nt in {"Field", "Method"}:
                item_name = (data.get("name") or "").strip().lower()
                if item_name and len(item_name) >= 5 and ("_" in item_name or item_name.startswith("x_")):
                    if item_name not in _GENERIC_FIELD_NAMES:
                        pattern = r"(?<!\w)" + re.escape(item_name) + r"(?!\w)"
                        if re.search(pattern, query_lower):
                            fp = data.get("filepath", "")
                            if fp:
                                for parent in Path(fp).parents:
                                    if (parent / "__manifest__.py").exists() and G.has_node(f"module:{parent.name}"):
                                        if parent.name not in generic_module_words and parent.name not in found:
                                            found.append(parent.name)
                                        break
    return found


def _specificity_score(technical_name: str, query_lower: str) -> Tuple[int, int, int, int, int, int, int]:
    """Deterministic specificity score for an exact technical model mention."""
    is_explicit = 1 if re.search(r"\b(?:mod[èe]le|model)\s+['\"]?" + re.escape(technical_name.lower()) + r"['\"]?\b", query_lower) else 0

    has_context_mention = 0
    for part in technical_name.split("."):
        if len(part) >= 4 and re.search(r"(?<!\w)" + re.escape(part.lower()) + r"(?!\w)", query_lower):
            has_context_mention = 1
            break
    if not has_context_mention:
        for alias, targets in BUSINESS_ALIASES_NFC.items():
            if technical_name in targets:
                pat = _ALIAS_PATTERNS.get(alias)
                if pat and pat.search(query_lower):
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
    top_score = max(score for _m, score in scored)
    return [m for m, score in scored if score == top_score]


def _fuzzy_match_graph(query: str, G, threshold: int = 75, limit: int = 5) -> List[Tuple[str, float]]:
    """Fuzzy match query against indexed graph node labels and models."""
    index = _build_fuzzy_index(G)
    if not index:
        return []

    labels = [entry[0] for entry in index]
    query_lower = query.lower()
    query_token_count = max(len(query_lower.split()), 1)

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
            label_token_count = max(len(label.split()), 1)
            length_penalty = min(label_token_count / query_token_count, 1.0) ** 0.5
            adjusted = score * length_penalty
            if adjusted >= threshold:
                model = index[idx][1]
                model_scores[model] = max(model_scores.get(model, 0.0), adjusted)

    sorted_results = sorted(model_scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_results[:limit]
