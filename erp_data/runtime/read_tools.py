"""Typed read-only ORM tools 
Each call validates inputs, executes under the requester identity via
XML-RPC, and returns an OrmToolResult (Observation + Evidence + text).
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from core.evidence import EvidenceSourceType, make_evidence
from erp_data.odoo_connector import FIELD_ATTRIBUTES, OdooConnector, OdooConnectorError
from erp_data.runtime.discovery import is_undescribed, mark_described, require_described
from erp_data.runtime.errors import OrmRuntimeError
from erp_data.runtime.identity import require_execution_uid, resolve_company_scope
from erp_data.runtime.types import OrmObservation, OrmToolResult
from erp_data.runtime.validation import (
    assert_domain_within_companies,
    assert_selection_values,
    cap_name_search_limit,
    cap_row_limit,
    validate_domain,
    validate_field_list,
    validate_groupby,
    validate_model_name,
    validate_name_search_operator,
    validate_order,
    validate_record_ids,
)

MODEL_NOT_FOUND_HINT = " Find the right model with list_models and one keyword."
TO_MANY_TYPES = frozenset({"many2many", "one2many"})

_connector: Optional[OdooConnector] = None
_FIELD_CACHE_MAX = 2048
_field_cache: dict[tuple[str, str], Optional[dict]] = {}


def _fold(text: str) -> str:
    """Case- and accent-insensitive form of a text, so a keyword matches a label however it is accented."""
    return "".join(char for char in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(char))


def _get_connector() -> OdooConnector:
    global _connector
    if _connector is None:
        _connector = OdooConnector()
    return _connector


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _window(rows: list, capped: int) -> tuple[list, bool]:
    """Cut rows fetched with capped + 1 to capped; truncated only when a further row exists."""
    return rows[:capped], len(rows) > capped


def _build_result(
    *,
    tool: str,
    method: str,
    model: str,
    request: dict[str, Any],
    value: Any,
    claim: str,
    row_count: int,
    truncated: bool,
    uid: int,
) -> OrmToolResult:
    read_at = _now_iso()
    company_id, company_ids = resolve_company_scope()
    observation = OrmObservation(
        tool=tool,
        model=model,
        method=method,
        request=request,
        row_count=row_count,
        truncated=truncated,
        execution_identity=uid,
        read_at=read_at,
        company_id=company_id,
        company_ids=company_ids,
    )
    scope = {
        "execution_identity": uid,
        "read_at": read_at,
        "model": model,
        "method": method,
        "row_count": row_count,
        "truncated": truncated,
        "request": request,
    }
    if company_id is not None:
        scope["company_id"] = company_id
    if company_ids is not None:
        scope["company_ids"] = company_ids
    evidence = make_evidence(
        source_type=EvidenceSourceType.ORM,
        claim=claim,
        source=f"orm_runtime.{tool}",
        value=value,
        scope=scope,
    )
    text = claim
    if truncated:
        text = f"{claim} [truncated]"
    return OrmToolResult(observation=observation, evidence=[evidence], text=text)


def _field_info(model: str, name: str) -> Optional[dict]:
    """fields_get metadata of one field, cached per model and field.

    None when unavailable; {} when Odoo answered and the field does not exist on the model."""
    key = (model, name)
    if key not in _field_cache:
        if len(_field_cache) >= _FIELD_CACHE_MAX:
            _field_cache.clear()
        uid = require_execution_uid()
        try:
            fields = _get_connector().fields_get(uid, model, [name])
        except OdooConnectorError:
            return None
        _field_cache[key] = (fields.get(name) or {}) if isinstance(fields, dict) else None
    return _field_cache[key]


def _with_relation_names(records: list[dict], model: str, fields: list[str]) -> list[dict]:
    """Odoo returns a to-many field as bare ids: give each id its name, as a many2one does ([id, name])."""
    uid = require_execution_uid()
    for name in fields:
        info = _field_info(model, name)
        if not info or info.get("type") not in TO_MANY_TYPES:
            continue
        ids = sorted({i for record in records for i in record.get(name) or [] if isinstance(i, int)})
        if not ids:
            continue
        try:
            rows = _get_connector().read(uid, info["relation"], ids, fields=["display_name"])
        except OdooConnectorError:
            continue
        names = {row["id"]: row["display_name"] for row in rows}
        for record in records:
            record[name] = [[i, names.get(i, str(i))] for i in record.get(name) or []]
    return records


def _selection_choices(model: str, path: str) -> Optional[list]:
    """Selection pairs of a field path such as `state` or `order_id.state`."""
    *parents, name = path.split(".")
    for parent in parents:
        info = _field_info(model, parent)
        model = info.get("relation") if info else None
        if not model:
            return None
    info = _field_info(model, name)
    return info.get("selection") if info and info.get("type") == "selection" else None


def _assert_domain_fields_exist(model: str, domain: list) -> None:
    """Refuse a domain leaf on a field or relation path absent from Odoo's schema."""
    for item in domain:
        if not isinstance(item, (list, tuple)) or len(item) != 3 or not isinstance(item[0], str):
            continue
        path = item[0]
        current_model = model
        parts = path.split(".")
        for index, name in enumerate(parts):
            info = _field_info(current_model, name)
            if info is None:
                break
            if info == {}:
                try:
                    known = sorted(_get_connector().fields_get(require_execution_uid(), current_model, []) or {})
                except OdooConnectorError:
                    known = []
                close = difflib.get_close_matches(name, known, n=5, cutoff=0.4)
                hint = f"closest fields: {', '.join(close)}; " if close else ""
                raise OrmRuntimeError(
                    f"unknown field {path!r} in domain: {current_model} has no such field; {hint}"
                    "read the full field list with fields_get"
                )
            if index < len(parts) - 1:
                current_model = info.get("relation")
                if not current_model:
                    raise OrmRuntimeError(
                        f"invalid relation path {path!r} in domain: {model}.{name} is not relational"
                    )


def _checked_domain(model: str, domain: Optional[list]) -> list:
    domain = validate_domain(domain)
    _company_id, company_ids = resolve_company_scope()
    assert_domain_within_companies(domain, company_ids)
    _assert_domain_fields_exist(model, domain)
    assert_selection_values(domain, lambda path: _selection_choices(model, path))
    return domain


def _short_odoo_error(message: str) -> str:
    """Keep the connector prefix and the final exception line of an Odoo XML-RPC traceback."""
    if "Traceback" not in message:
        return message
    lines = [line.strip().rstrip("'>").strip() for line in re.split(r"\\n|\n", message)]
    last = [line for line in lines if line][-1].replace("\\'", "'")
    prefix = message.split("<Fault", 1)[0].strip()
    return f"{prefix} {last}".strip()


def _run_validated(call: Callable[[], Any]) -> Any:
    try:
        return call()
    except OrmRuntimeError:
        raise
    except OdooConnectorError as exc:
        message = _short_odoo_error(str(exc))
        if "doesn't exist" in message:
            message += MODEL_NOT_FOUND_HINT
        raise OrmRuntimeError(message) from exc


def _field_summary(metadata: dict) -> str:
    relation = f"({metadata['relation']})" if metadata.get("relation") else ""
    return f"{metadata.get('type')}{relation}: {metadata.get('string')}"


def orm_fields_get(model: str, field_names: Optional[list] = None) -> OrmToolResult:
    model = validate_model_name(model)
    names = validate_field_list(field_names or None)
    uid = require_execution_uid()
    request = {"model": model, "field_names": names}
    # A partial read on a model not yet described in full is widened: one call satisfies the schema guard
    # and the model sees every field, with the requested ones in detail.
    widened = bool(names) and is_undescribed(model)
    fields_info = _run_validated(lambda: _get_connector().fields_get(uid, model, None if widened else names))
    described = {
        name: metadata for name, metadata in sorted(fields_info.items()) if isinstance(metadata, dict)
    } if isinstance(fields_info, dict) else {}
    fields = {
        name: {
            key: metadata[key]
            for key in FIELD_ATTRIBUTES
            if key in metadata
        } if name in names else _field_summary(metadata)
        for name, metadata in described.items()
    }
    value = {"field_count": len(fields), "fields": fields}
    unknown = [name for name in names if name not in fields]
    if unknown:
        value["unknown_fields"] = unknown
    if widened:
        value["note"] = f"{model} was not described yet: all its fields are listed, those you asked for in detail"
    if not names or widened:
        mark_described(model)
    return _build_result(
        tool="fields_get",
        method="fields_get",
        model=model,
        request=request,
        value=value,
        claim=f"{model}: {len(fields)} fields described by fields_get",
        row_count=len(fields),
        truncated=False,
        uid=uid,
    )


def orm_search(
    model: str,
    domain: Optional[list] = None,
    limit: Optional[int] = None,
    order: Optional[str] = None,
    offset: int = 0,
) -> OrmToolResult:
    model = validate_model_name(model)
    require_described(model)
    domain = _checked_domain(model, domain)
    order = validate_order(order)
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise OrmRuntimeError("offset must be a non-negative integer")
    capped = cap_row_limit(limit)
    uid = require_execution_uid()
    request = {
        "model": model,
        "domain": domain,
        "limit": capped,
        "order": order,
        "offset": offset,
    }
    ids, truncated = _window(_run_validated(
        lambda: _get_connector().search(
            uid, model, domain=domain, limit=capped + 1, order=order, offset=offset
        )
    ), capped)
    return _build_result(
        tool="search",
        method="search",
        model=model,
        request=request,
        value=ids,
        claim=f"{model}.search -> {len(ids)} ids",
        row_count=len(ids),
        truncated=truncated,
        uid=uid,
    )


def orm_read(
    model: str,
    ids: list[int],
    fields: Optional[list[str]] = None,
) -> OrmToolResult:
    model = validate_model_name(model)
    capped_max = cap_row_limit(None)
    ids = validate_record_ids(ids, max_rows=capped_max)
    fields = validate_field_list(fields)
    if not fields:
        raise OrmRuntimeError("fields must be an explicit non-empty list for read")
    uid = require_execution_uid()
    request = {"model": model, "ids": ids, "fields": fields}
    records = _with_relation_names(
        _run_validated(lambda: _get_connector().read(uid, model, ids, fields=fields)), model, fields
    )
    return _build_result(
        tool="read",
        method="read",
        model=model,
        request=request,
        value=records,
        claim=f"{model}.read -> {len(records)} records",
        row_count=len(records),
        truncated=False,
        uid=uid,
    )


def orm_search_read(
    model: str,
    domain: Optional[list] = None,
    fields: Optional[list[str]] = None,
    limit: Optional[int] = None,
    order: Optional[str] = None,
    context: Optional[dict] = None,
) -> OrmToolResult:
    model = validate_model_name(model)
    require_described(model)
    domain = _checked_domain(model, domain)
    fields = validate_field_list(fields)
    if not fields:
        raise OrmRuntimeError(
            "fields must be an explicit non-empty list for search_read"
        )
    order = validate_order(order)
    capped = cap_row_limit(limit)
    uid = require_execution_uid()
    request = {
        "model": model,
        "domain": domain,
        "fields": fields,
        "limit": capped,
        "order": order,
    }
    if context:
        request["context"] = context
    extra = {"context": context} if context else {}
    records, truncated = _window(_run_validated(
        lambda: _get_connector().search_read(
            uid=uid,
            model=model,
            domain=domain,
            fields=fields,
            limit=capped + 1,
            order=order,
            **extra,
        )
    ), capped)
    records = _with_relation_names(records, model, fields)
    return _build_result(
        tool="search_read",
        method="search_read",
        model=model,
        request=request,
        value=records,
        claim=f"{model}.search_read -> {len(records)} records",
        row_count=len(records),
        truncated=truncated,
        uid=uid,
    )


def orm_search_count(model: str, domain: Optional[list] = None) -> OrmToolResult:
    model = validate_model_name(model)
    require_described(model)
    domain = _checked_domain(model, domain)
    uid = require_execution_uid()
    request = {"model": model, "domain": domain}
    count = _run_validated(
        lambda: _get_connector().search_count(uid=uid, model=model, domain=domain)
    )
    return _build_result(
        tool="search_count",
        method="search_count",
        model=model,
        request=request,
        value=count,
        claim=f"{model}.search_count -> {count}",
        row_count=1,
        truncated=False,
        uid=uid,
    )


def _with_currency_groupby(model: str, fields: list[str], groupby: list[str]) -> list[str]:
    """Add the stored currency field of each aggregated monetary field, so amounts of different currencies are never summed."""
    extended = list(groupby)
    for spec in fields:
        info = _field_info(model, spec.split(":")[0])
        currency = info.get("currency_field") if info and info.get("type") == "monetary" else None
        if currency and currency not in extended and (_field_info(model, currency) or {}).get("store"):
            extended.append(currency)
    return extended


def orm_read_group(
    model: str,
    domain: Optional[list],
    fields: list[str],
    groupby: Optional[list[str]] = None,
    lazy: bool = True,
) -> OrmToolResult:
    model = validate_model_name(model)
    require_described(model)
    domain = _checked_domain(model, domain)
    fields = validate_field_list(fields, allow_aggregate=True)
    if not fields:
        raise OrmRuntimeError("fields must be a non-empty list for read_group")
    groupby = validate_groupby(groupby)
    grouped = _with_currency_groupby(model, fields, groupby)
    lazy = lazy and grouped == groupby
    groupby = grouped
    uid = require_execution_uid()
    request = {
        "model": model,
        "domain": domain,
        "fields": fields,
        "groupby": groupby,
        "lazy": lazy,
    }
    rows = _run_validated(
        lambda: _get_connector().read_group(
            uid=uid,
            model=model,
            domain=domain,
            fields=fields,
            groupby=groupby,
            lazy=lazy,
        )
    )
    rows, truncated = _window(rows, cap_row_limit(None))
    return _build_result(
        tool="read_group",
        method="read_group",
        model=model,
        request=request,
        value=rows,
        claim=f"{model}.read_group -> {len(rows)} groups",
        row_count=len(rows),
        truncated=truncated,
        uid=uid,
    )


def orm_name_search(
    model: str,
    name: str = "",
    domain: Optional[list] = None,
    operator: str = "ilike",
    limit: Optional[int] = None,
) -> OrmToolResult:
    model = validate_model_name(model)
    if not isinstance(name, str):
        raise OrmRuntimeError("name must be a string")
    operator = validate_name_search_operator(operator)
    domain = _checked_domain(model, domain)
    capped = cap_name_search_limit(limit)
    uid = require_execution_uid()
    request = {
        "model": model,
        "name": name,
        "domain": domain,
        "operator": operator,
        "limit": capped,
    }
    pairs, truncated = _window(_run_validated(
        lambda: _get_connector().name_search(
            uid, model, name=name, domain=domain, operator=operator, limit=capped + 1
        )
    ), capped)
    return _build_result(
        tool="name_search",
        method="name_search",
        model=model,
        request=request,
        value=pairs,
        claim=f"{model}.name_search({name!r}) -> {len(pairs)} matches",
        row_count=len(pairs),
        truncated=truncated,
        uid=uid,
    )


def orm_list_models(query: str) -> OrmToolResult:
    if not isinstance(query, str) or not query.strip():
        raise OrmRuntimeError("query must be a keyword of the model name or label")
    words = _fold(query).split()
    uid = require_execution_uid()
    rows = _run_validated(lambda: _get_connector().available_models(uid))
    matches = sorted(
        (row["model"], row["display_name"])
        for row in rows
        if all(word in _fold(f"{row['model']} {row['display_name']}") for word in words)
    )
    namespaces = {
        model.split(".", 1)[0]
        for model, _label in matches
        if len(words) == 1 and "." in model
    }
    expanded = sorted(
        (row["model"], row["display_name"])
        for row in rows
        if row["model"].split(".", 1)[0] in namespaces
        and (row["model"], row["display_name"]) not in matches
    )
    candidates = matches + expanded
    shown, truncated = _window(matches, cap_row_limit(None))
    if expanded:
        shown, truncated = _window(candidates, cap_row_limit(None))
    return _build_result(
        tool="list_models",
        method="get_available_models",
        model="ir.model",
        request={"query": query},
        value=shown,
        claim=f"models matching {query!r} -> {len(shown)} models",
        row_count=len(shown),
        truncated=truncated,
        uid=uid,
    )


SCHEMA_METHODS = frozenset({"fields_get", "get_available_models"})

READ_ONLY_ORM_TOOLS: dict[str, Callable[..., OrmToolResult]] = {
    "list_models": orm_list_models,
    "fields_get": orm_fields_get,
    "search": orm_search,
    "read": orm_read,
    "search_read": orm_search_read,
    "search_count": orm_search_count,
    "read_group": orm_read_group,
    "name_search": orm_name_search,
}
