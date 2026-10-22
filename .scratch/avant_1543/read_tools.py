"""Typed read-only ORM tools (P9 first lot).

Each call validates inputs, executes under the requester identity via
XML-RPC, and returns an OrmToolResult (Observation + Evidence + text).
No generic execute_kw is exposed to the LLM.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from core.evidence.evidence import EvidenceSourceType, make_evidence
from erp_data.odoo_connector import OdooConnector, OdooConnectorError
from erp_data.runtime.errors import OrmRuntimeError
from erp_data.runtime.identity import require_execution_uid, resolve_company_scope
from erp_data.runtime.types import OrmObservation, OrmToolResult
from erp_data.runtime.validation import (
    assert_domain_within_companies,
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

_connector: Optional[OdooConnector] = None


def _get_connector() -> OdooConnector:
    global _connector
    if _connector is not None:
        return _connector
    from erp_data._odoo_helpers import connector as shared

    return shared


def set_connector_for_tests(connector: Optional[OdooConnector]) -> None:
    global _connector
    _connector = connector


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _checked_domain(domain: Optional[list]) -> list:
    domain = validate_domain(domain)
    _company_id, company_ids = resolve_company_scope()
    assert_domain_within_companies(domain, company_ids)
    return domain


def _run_validated(call: Callable[[], Any]) -> Any:
    try:
        return call()
    except OrmRuntimeError:
        raise
    except OdooConnectorError as exc:
        raise OrmRuntimeError(str(exc)) from exc


def orm_fields_get(model: str) -> OrmToolResult:
    model = validate_model_name(model)
    uid = require_execution_uid()
    request = {"model": model}
    fields_info = _run_validated(lambda: _get_connector().fields_get(uid, model))
    fields = {
        name: {
            key: metadata[key]
            for key in ("string", "type", "help", "relation", "selection", "required", "readonly", "store")
            if key in metadata
        }
        for name, metadata in sorted(fields_info.items())
        if isinstance(metadata, dict)
    } if isinstance(fields_info, dict) else {}
    return _build_result(
        tool="fields_get",
        method="fields_get",
        model=model,
        request=request,
        value={"field_count": len(fields), "fields": fields},
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
    domain = _checked_domain(domain)
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
    ids = _run_validated(
        lambda: _get_connector().search(
            uid, model, domain=domain, limit=capped, order=order, offset=offset
        )
    )
    truncated = len(ids) >= capped
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
    records = _run_validated(
        lambda: _get_connector().read(uid, model, ids, fields=fields)
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
    domain = _checked_domain(domain)
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
    records = _run_validated(
        lambda: _get_connector().search_read(
            uid=uid,
            model=model,
            domain=domain,
            fields=fields,
            limit=capped,
            order=order,
            **extra,
        )
    )
    truncated = len(records) >= capped
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
    domain = _checked_domain(domain)
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


def orm_read_group(
    model: str,
    domain: Optional[list],
    fields: list[str],
    groupby: list[str],
    lazy: bool = True,
) -> OrmToolResult:
    model = validate_model_name(model)
    domain = _checked_domain(domain)
    fields = validate_field_list(fields, allow_aggregate=True)
    if not fields:
        raise OrmRuntimeError("fields must be a non-empty list for read_group")
    groupby = validate_groupby(groupby)
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
    capped = cap_row_limit(None)
    truncated = len(rows) >= capped
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
    domain = _checked_domain(domain)
    capped = cap_name_search_limit(limit)
    uid = require_execution_uid()
    request = {
        "model": model,
        "name": name,
        "domain": domain,
        "operator": operator,
        "limit": capped,
    }
    pairs = _run_validated(
        lambda: _get_connector().name_search(
            uid, model, name=name, domain=domain, operator=operator, limit=capped
        )
    )
    truncated = len(pairs) >= capped
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


READ_ONLY_ORM_TOOLS: dict[str, Callable[..., OrmToolResult]] = {
    "fields_get": orm_fields_get,
    "search": orm_search,
    "read": orm_read,
    "search_read": orm_search_read,
    "search_count": orm_search_count,
    "read_group": orm_read_group,
    "name_search": orm_name_search,
}
