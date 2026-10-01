"""Read translated model and field labels from a live Odoo registry."""

from typing import Iterable, List, Optional, Tuple


def _active_requested_languages(
    requested_languages: Iterable[str],
    active_languages: Optional[Iterable[str]],
) -> List[str]:
    if active_languages is None:
        return []
    active_by_base = {}
    for language in active_languages:
        normalized = str(language or "").strip().replace("-", "_")
        if normalized:
            active_by_base.setdefault(normalized.casefold().split("_", 1)[0], normalized)
    selected = []
    for language in requested_languages:
        base = str(language or "").strip().casefold().replace("-", "_").split("_", 1)[0]
        active_language = active_by_base.get(base)
        if active_language and active_language not in selected:
            selected.append(active_language)
    return selected


def _runtime_model_labels(records: Iterable[dict], language: str) -> List[dict]:
    labels = []
    for record in records:
        model = str(record.get("model") or "").strip()
        label = str(record.get("name") or "").strip()
        if model and label:
            labels.append({
                "node_id": f"model:{model}",
                "label": label,
                "language": language,
                "entity_type": "model",
                "reference": f"ir.model:{model}",
            })
    return labels


def _runtime_field_labels(records: Iterable[dict], language: str) -> List[dict]:
    labels = []
    for record in records:
        model = str(record.get("model") or "").strip()
        field_name = str(record.get("name") or "").strip()
        label = str(record.get("field_description") or "").strip()
        if model and field_name and label:
            labels.append({
                "node_id": f"field:{model}.{field_name}",
                "label": label,
                "language": language,
                "entity_type": "field",
                "reference": f"ir.model.fields:{model}.{field_name}",
            })
    return labels


def read_runtime_translations(
    connector,
    uid: int,
    requested_languages: Iterable[str],
    active_languages: Optional[Iterable[str]],
) -> Tuple[List[dict], dict]:
    """Read labels only for active requested languages and return a coverage summary."""
    languages = _active_requested_languages(requested_languages, active_languages)
    summary = {
        "active_languages_available": active_languages is not None,
        "requested_languages": sorted({str(language) for language in requested_languages if language}),
        "queried_languages": languages,
        "model_records": 0,
        "field_records": 0,
        "failed_languages": [],
    }
    labels = []
    for language in languages:
        try:
            context = {"lang": language}
            model_records = connector.search_read(
                uid=uid,
                model="ir.model",
                fields=["model", "name"],
                context=context,
            )
            field_records = connector.search_read(
                uid=uid,
                model="ir.model.fields",
                fields=["model", "name", "field_description"],
                context=context,
            )
        except Exception:
            summary["failed_languages"].append(language)
            continue
        summary["model_records"] += len(model_records)
        summary["field_records"] += len(field_records)
        labels.extend(_runtime_model_labels(model_records, language))
        labels.extend(_runtime_field_labels(field_records, language))
    return labels, summary
