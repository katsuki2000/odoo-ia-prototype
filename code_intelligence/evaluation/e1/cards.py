"""Build short human-readable node cards from a code-intelligence graph (E1 only)."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional, Sequence


CARD_NODE_TYPES = (
    "Model",
    "Menu",
    "Field",
    "Method",
    "Group",
    "Rule",
    "Button",
)


@dataclass(frozen=True)
class NodeCard:
    object_ref: str
    node_type: str
    text: str
    text_hash: str
    module: str = ""


def _language_base(value: Optional[str]) -> str:
    return str(value or "").casefold().split("_", 1)[0]


def _language_matches(candidate_language: object, language: Optional[str]) -> bool:
    if not language:
        return True
    candidate_base = _language_base(str(candidate_language or ""))
    language_base = _language_base(language)
    return not candidate_base or candidate_base == language_base


_STOPWORDS = frozenset({
    # French
    "comment", "faire", "une", "un", "le", "la", "les", "de", "des", "du",
    "et", "ou", "pour", "dans", "sur", "avec", "mon", "ma", "mes", "je",
    "on", "ce", "cet", "cette", "qui", "que", "quoi", "est", "sont", "au",
    "aux", "par", "pas", "plus", "les",
    # English
    "how", "do", "does", "did", "the", "a", "an", "to", "for", "of", "and",
    "or", "in", "on", "my", "is", "are", "be", "with", "from", "what", "where",
})


def tokenize(text: str, *, drop_stopwords: bool = False) -> list[str]:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    tokens = [token for token in re.findall(r"[^\W_]+", normalized, flags=re.UNICODE) if len(token) > 1]
    if drop_stopwords:
        tokens = [token for token in tokens if token not in _STOPWORDS]
    return tokens


def _labels(data: dict, language: Optional[str]) -> list[str]:
    labels: list[str] = []
    for key in ("description", "label", "name"):
        value = str(data.get(key) or "").strip()
        if value:
            labels.append(value)

    matched: list[str] = []
    fallback: list[str] = []
    for translation in data.get("business_labels") or []:
        label = str(translation.get("label") or "").strip()
        if not label:
            continue
        fallback.append(label)
        if _language_matches(translation.get("language"), language):
            matched.append(label)
    # If the graph has no labels in the query language (common when
    # translations were not attached), keep other languages rather than
    # leaving only the English description/technical name.
    labels.extend(matched or fallback)

    for action in data.get("window_actions") or []:
        name = str(action.get("name") or "").strip()
        if name:
            labels.append(name)
    return list(dict.fromkeys(label for label in labels if label))


def object_ref_of(node_id: str, data: dict) -> Optional[str]:
    node_type = data.get("node_type")
    if node_type == "Model":
        name = str(data.get("name") or "").strip()
        return f"model:{name}" if name else None
    if node_type == "Menu":
        xml_id = str(data.get("xml_id") or "").strip()
        return f"menu:{xml_id}" if xml_id else None
    if node_type == "Field":
        model = str(data.get("model") or "").strip()
        name = str(data.get("name") or "").strip()
        return f"field:{model}.{name}" if model and name else None
    if node_type == "Method":
        model = str(data.get("model") or "").strip()
        name = str(data.get("name") or "").strip()
        return f"method:{model}.{name}" if model and name else None
    if node_type == "Group":
        xml_id = str(data.get("xml_id") or "").strip()
        return f"group:{xml_id}" if xml_id else None
    if node_type == "Rule":
        xml_id = str(data.get("xml_id") or "").strip()
        return f"rule:{xml_id}" if xml_id else None
    if node_type == "Button":
        # prefer graph id when present
        if isinstance(node_id, str) and node_id.startswith("button:"):
            return node_id
        name = str(data.get("name") or data.get("xml_id") or "").strip()
        model = str(data.get("model") or "").strip()
        if model and name:
            return f"button:{model}.{name}"
    return None


def _module_of(data: dict) -> str:
    module = str(data.get("module") or "").strip()
    if module:
        return module
    for action in data.get("window_actions") or []:
        module = str(action.get("module") or "").strip()
        if module:
            return module
    for path in data.get("filepaths") or []:
        parts = str(path).replace("\\", "/").split("/")
        if "addons" in parts:
            index = parts.index("addons")
            if index + 1 < len(parts):
                return parts[index + 1]
    filepath = str(data.get("filepath") or "")
    parts = filepath.replace("\\", "/").split("/")
    if "addons" in parts:
        index = parts.index("addons")
        if index + 1 < len(parts):
            return parts[index + 1]
    return ""


def _menu_paths(graph, model_node_id: str, language: Optional[str]) -> list[str]:
    paths: list[str] = []
    # CHILD_OF: source = child menu, target = parent menu
    parent_of: dict[str, str] = {}
    for source, target, data in graph.edges(data=True):
        if data.get("edge_type") == "CHILD_OF":
            parent_of[str(source)] = str(target)

    def climb(menu_id: str, budget: int = 6) -> list[str]:
        names: list[str] = []
        current = menu_id
        seen = set()
        while current and current not in seen and budget > 0:
            seen.add(current)
            data = graph.nodes.get(current) or {}
            if data.get("node_type") == "Menu":
                labels = _labels(data, language)
                names.append(labels[0] if labels else str(data.get("xml_id") or current))
            current = parent_of.get(current)
            budget -= 1
        names.reverse()
        return names

    for source, target, data in graph.in_edges(model_node_id, data=True):
        if data.get("edge_type") != "OPENS_MODEL":
            continue
        chain = climb(str(source))
        if chain:
            paths.append(" > ".join(chain))
    return list(dict.fromkeys(paths))


def build_node_cards(
    graph,
    *,
    language: Optional[str] = None,
    node_types: Sequence[str] = CARD_NODE_TYPES,
) -> list[NodeCard]:
    """Return one card per selected graph node; relations stay on edges, not embedded."""
    allowed = set(node_types)
    cards: list[NodeCard] = []
    for node_id, data in graph.nodes(data=True):
        node_type = data.get("node_type")
        if node_type not in allowed:
            continue
        object_ref = object_ref_of(str(node_id), data)
        if not object_ref:
            continue
        labels = _labels(data, language)
        module = _module_of(data)
        parts = [
            f"type: {str(node_type).lower()}",
            f"id: {object_ref}",
        ]
        if module:
            parts.append(f"module: {module}")
        if labels:
            parts.append("labels: " + " ; ".join(labels))
        if node_type == "Model":
            menus = _menu_paths(graph, str(node_id), language)
            if menus:
                parts.append("menus: " + " | ".join(menus))
            technical = str(data.get("name") or "").strip()
            if technical:
                parts.append(f"technical: {technical}")
        if node_type == "Field":
            parts.append(f"model: {data.get('model')}")
            parts.append(f"field_type: {data.get('field_type')}")
        if node_type == "Method":
            parts.append(f"model: {data.get('model')}")
        if node_type == "Menu":
            groups = data.get("groups") or []
            if groups:
                parts.append("groups: " + ", ".join(str(g) for g in groups))
        text = "\n".join(parts)
        cards.append(
            NodeCard(
                object_ref=object_ref,
                node_type=str(node_type),
                text=text,
                text_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                module=module,
            )
        )
    cards.sort(key=lambda card: card.object_ref)
    return cards
