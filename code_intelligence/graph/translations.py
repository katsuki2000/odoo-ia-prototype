"""Parse and attach Odoo gettext translations to graph entities."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional

from code_intelligence.utils import qualify_xml_id


@dataclass(frozen=True)
class TranslationEntry:
    msgid: str
    msgstr: str
    references: tuple[str, ...]
    language: str
    module: str
    source: str = "po"


def _po_string(value: str) -> str:
    try:
        result = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return ""
    return result if isinstance(result, str) else ""


def parse_po(path: Path, module: str, language: Optional[str] = None) -> list[TranslationEntry]:
    """Read standard GNU PO entries, including folded strings and references."""
    language = language or _language_from_path(path)
    entries: list[TranslationEntry] = []
    fields: dict[str, str] = {}
    references: list[str] = []
    current_field: Optional[str] = None

    def finish() -> None:
        msgid = fields.get("msgid", "")
        msgstr = fields.get("msgstr", "")
        if msgid and msgstr.strip():
            entries.append(TranslationEntry(
                msgid=msgid,
                msgstr=msgstr,
                references=tuple(references),
                language=language,
                module=module,
            ))

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            finish()
            fields = {}
            references = []
            current_field = None
        elif stripped.startswith("#:"):
            references.extend(stripped[2:].split())
        elif stripped.startswith("msgid "):
            current_field = "msgid"
            fields[current_field] = _po_string(stripped[6:])
        elif stripped.startswith("msgstr "):
            current_field = "msgstr"
            fields[current_field] = _po_string(stripped[7:])
        elif stripped.startswith("msgid_plural "):
            current_field = None
        elif stripped.startswith("msgstr["):
            current_field = None
        elif stripped.startswith('"') and current_field:
            fields[current_field] = fields.get(current_field, "") + _po_string(stripped)
        elif stripped.startswith(("#", "msgctxt ", "#,")):
            current_field = None
    finish()
    return entries


def _language_from_path(path: Path) -> str:
    return path.stem


def load_module_translations(
    module_dir: Path,
    module: str,
    languages: Optional[Iterable[str]] = None,
) -> list[TranslationEntry]:
    entries: list[TranslationEntry] = []
    if not languages:
        return entries
    requested = {language.lower() for language in languages}
    translation_dir = module_dir / "i18n"
    if not translation_dir.is_dir():
        return entries
    catalogs = {path.stem.lower(): path for path in translation_dir.glob("*.po")}
    selected_paths = set()
    for language in requested:
        path = catalogs.get(language)
        if path is None:
            path = catalogs.get(language.split("_", 1)[0])
        if path is not None:
            selected_paths.add(path)
    for path in sorted(selected_paths):
        try:
            entries.extend(parse_po(path, module))
        except (OSError, UnicodeError):
            continue
    return entries


def _model_from_xmlid(xmlid: str, graph) -> Optional[str]:
    local_id = xmlid.split(".", 1)[-1]
    if not local_id.startswith("model_"):
        return None
    slug = local_id[len("model_"):]
    matches = [
        data.get("name", node_id.removeprefix("model:"))
        for node_id, data in graph.nodes(data=True)
        if data.get("node_type") == "Model"
        and data.get("name", node_id.removeprefix("model:")).replace(".", "_") == slug
    ]
    return matches[0] if len(matches) == 1 else None


def _target_for_reference(reference: str, module: str, graph) -> Optional[tuple[str, str]]:
    match = re.match(r"model:ir\.model,name:([^\s]+)$", reference)
    if match:
        model = _model_from_xmlid(qualify_xml_id(match.group(1), module), graph)
        return (f"model:{model}", "model") if model else None

    match = re.match(r"model:ir\.model\.fields,field_description:([^\s]+)$", reference)
    if match:
        xmlid = qualify_xml_id(match.group(1), module)
        local_id = xmlid.split(".", 1)[-1]
        if local_id.startswith("field_") and "__" in local_id:
            model_slug, field_name = local_id[6:].split("__", 1)
            matches = [
                node_id for node_id, data in graph.nodes(data=True)
                if data.get("node_type") == "Field"
                and data.get("model", "").replace(".", "_") == model_slug
                and data.get("name") == field_name
            ]
            return (matches[0], "field") if len(matches) == 1 else None

    match = re.match(r"model:ir\.model\.fields\.selection,name:([^\s]+)$", reference)
    if match:
        local_id = qualify_xml_id(match.group(1), module).split(".", 1)[-1]
        if local_id.startswith("selection__"):
            pieces = local_id[len("selection__"):].split("__")
            if len(pieces) >= 3:
                model_slug, field_name = pieces[0], pieces[1]
                matches = [
                    node_id for node_id, data in graph.nodes(data=True)
                    if data.get("node_type") == "Field"
                    and data.get("model", "").replace(".", "_") == model_slug
                    and data.get("name") == field_name
                ]
                return (matches[0], "selection") if len(matches) == 1 else None

    match = re.match(r"model:ir\.ui\.menu,name:([^\s]+)$", reference)
    if match:
        xmlid = qualify_xml_id(match.group(1), module)
        node_id = f"menu:{xmlid}"
        return (node_id, "menu") if graph.has_node(node_id) else None
    return None


def attach_translations(graph, entries: Iterable[TranslationEntry]) -> dict[str, int]:
    attached = 0
    unlinked = 0
    for entry in entries:
        linked_for_entry = False
        for reference in entry.references:
            target = _target_for_reference(reference, entry.module, graph)
            if not target:
                continue
            node_id, entity_type = target
            labels = graph.nodes[node_id].setdefault("business_labels", [])
            record = {
                "label": entry.msgstr.strip(),
                "source_label": entry.msgid.strip(),
                "language": entry.language,
                "module": entry.module,
                "source": entry.source,
                "reference": reference,
                "entity_type": entity_type,
            }
            if record not in labels:
                labels.append(record)
            attached += 1
            linked_for_entry = True
        if not linked_for_entry:
            unlinked += 1
    return {"attached": attached, "unlinked": unlinked}


def attach_runtime_translations(graph, records: Iterable[dict]) -> dict[str, int]:
    attached = 0
    unlinked = 0
    expected_types = {"model": "Model", "field": "Field", "menu": "Menu", "selection": "Field"}
    for record in records:
        node_id = record.get("node_id")
        label = str(record.get("label") or "").strip()
        language = str(record.get("language") or "")
        entity_type = str(record.get("entity_type") or "")
        if (
            not node_id or not label or not language
            or entity_type not in expected_types
            or not graph.has_node(node_id)
            or graph.nodes[node_id].get("node_type") != expected_types[entity_type]
        ):
            unlinked += 1
            continue
        business_labels = graph.nodes[node_id].setdefault("business_labels", [])
        translated_label = {
            "label": label,
            "source_label": str(record.get("source_label") or ""),
            "language": language,
            "module": str(record.get("module") or ""),
            "source": "runtime",
            "reference": str(record.get("reference") or node_id),
            "entity_type": entity_type,
        }
        if translated_label not in business_labels:
            business_labels.append(translated_label)
            attached += 1
    return {"attached": attached, "unlinked": unlinked}


def translation_fingerprint(entries: Iterable[TranslationEntry]) -> str:
    payload = json.dumps(
        [asdict(entry) for entry in entries],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "TranslationEntry",
    "parse_po",
    "load_module_translations",
    "attach_translations",
    "attach_runtime_translations",
    "translation_fingerprint",
]
