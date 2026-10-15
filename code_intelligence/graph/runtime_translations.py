"""Read translated labels from a live Odoo registry."""

import logging
from typing import Iterable, List, Optional, Tuple

from erp_data.odoo_connector import OdooConnectorError

logger = logging.getLogger(__name__)


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


def _xmlid_by_res_id(connector, uid: int, model: str, res_ids: List[int], context: dict) -> dict:
    if not res_ids:
        return {}
    rows = connector.search_read(
        uid=uid,
        model="ir.model.data",
        domain=[("model", "=", model), ("res_id", "in", res_ids)],
        fields=["module", "name", "res_id"],
        context=context,
    )
    mapping = {}
    for row in rows:
        res_id = row.get("res_id")
        module = str(row.get("module") or "").strip()
        name = str(row.get("name") or "").strip()
        if res_id is not None and module and name:
            mapping[int(res_id)] = f"{module}.{name}"
    return mapping


def _runtime_group_labels(records: Iterable[dict], language: str, xmlids: dict) -> List[dict]:
    labels = []
    for record in records:
        res_id = record.get("id")
        label = str(record.get("name") or "").strip()
        xmlid = xmlids.get(int(res_id)) if res_id is not None else None
        if not xmlid or not label:
            continue
        labels.append({
            "node_id": f"group:{xmlid}",
            "label": label,
            "language": language,
            "entity_type": "group",
            "reference": f"res.groups:{xmlid}",
        })
    return labels


def _runtime_category_labels(records: Iterable[dict], language: str, xmlids: dict) -> List[dict]:
    labels = []
    for record in records:
        res_id = record.get("id")
        label = str(record.get("name") or "").strip()
        xmlid = xmlids.get(int(res_id)) if res_id is not None else None
        if not xmlid or not label:
            continue
        labels.append({
            "node_id": f"category:{xmlid}",
            "label": label,
            "source_label": label,
            "language": language,
            "entity_type": "category",
            "reference": f"ir.module.category:{xmlid}",
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
        "group_records": 0,
        "category_records": 0,
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
            group_records = connector.search_read(
                uid=uid,
                model="res.groups",
                fields=["id", "name", "category_id"],
                context=context,
            )
            category_records = connector.search_read(
                uid=uid,
                model="ir.module.category",
                fields=["id", "name"],
                context=context,
            )
            group_xmlids = _xmlid_by_res_id(
                connector,
                uid,
                "res.groups",
                [int(row["id"]) for row in group_records if row.get("id") is not None],
                context,
            )
            category_xmlids = _xmlid_by_res_id(
                connector,
                uid,
                "ir.module.category",
                [int(row["id"]) for row in category_records if row.get("id") is not None],
                context,
            )
        except OdooConnectorError as error:
            logger.warning("Could not read runtime translations for language %s: %s", language, error)
            summary["failed_languages"].append(language)
            continue
        summary["model_records"] += len(model_records)
        summary["field_records"] += len(field_records)
        summary["group_records"] += len(group_records)
        summary["category_records"] += len(category_records)
        labels.extend(_runtime_model_labels(model_records, language))
        labels.extend(_runtime_field_labels(field_records, language))
        labels.extend(_runtime_group_labels(group_records, language, group_xmlids))
        labels.extend(_runtime_category_labels(category_records, language, category_xmlids))
    return labels, summary
