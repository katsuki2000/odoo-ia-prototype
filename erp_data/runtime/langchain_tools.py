"""LangChain @tool wrappers over typed P9 ORM runtime reads."""

from __future__ import annotations

import json
from typing import Any, Optional

from langchain_core.tools import tool

from core.evidence.evidence_collector import record_evidence
from erp_data.runtime.errors import OrmRuntimeError
from erp_data.runtime.read_tools import (
    orm_fields_get as _fields_get,
    orm_name_search as _name_search,
    orm_read as _read,
    orm_read_group as _read_group,
    orm_search as _search,
    orm_search_count as _search_count,
    orm_search_read as _search_read,
)
from erp_data.runtime.types import OrmToolResult

_OBS_VALUE_CHARS = 4000


def _format_observation(result: OrmToolResult) -> str:
    payload = {
        "tool": result.observation.tool,
        "model": result.observation.model,
        "row_count": result.observation.row_count,
        "truncated": result.observation.truncated,
        "value": result.evidence[0].value if result.evidence else None,
    }
    body = json.dumps(payload, ensure_ascii=False, default=str)
    if len(body) > _OBS_VALUE_CHARS:
        body = body[: _OBS_VALUE_CHARS] + "...[truncated]"
    return f"{result.text}\n{body}"


def _invoke(call) -> str:
    try:
        result = call()
    except OrmRuntimeError as exc:
        return f"ORM read refused: {exc}"
    record_evidence(result.evidence)
    return _format_observation(result)


@tool
def fields_get(model: str) -> str:
    """Inspect field names and types for an Odoo model (schema only)."""
    return _invoke(lambda: _fields_get(model))


@tool
def search(
    model: str,
    domain: Optional[list] = None,
    limit: int = 0,
    order: str = "",
    offset: int = 0,
) -> str:
    """Return record ids for a model matching an Odoo domain. Does not return field values."""
    return _invoke(
        lambda: _search(
            model,
            domain=domain or [],
            limit=limit or None,
            order=order or None,
            offset=offset,
        )
    )


@tool
def read(model: str, ids: list[int], fields: list[str]) -> str:
    """Read explicit fields for known record ids. fields must be non-empty."""
    return _invoke(lambda: _read(model, ids=ids, fields=fields))


@tool
def search_read(
    model: str,
    domain: Optional[list] = None,
    fields: Optional[list[str]] = None,
    limit: int = 0,
    order: str = "",
) -> str:
    """Search then read: return records matching domain with the requested fields only."""
    return _invoke(
        lambda: _search_read(
            model,
            domain=domain or [],
            fields=fields,
            limit=limit or None,
            order=order or None,
        )
    )


@tool
def search_count(model: str, domain: Optional[list] = None) -> str:
    """Count records matching an Odoo domain (how many)."""
    return _invoke(lambda: _search_count(model, domain=domain or []))


@tool
def read_group(
    model: str,
    fields: list[str],
    groupby: list[str],
    domain: Optional[list] = None,
    lazy: bool = True,
) -> str:
    """Aggregate with read_group. fields may use aggregates like amount_total:sum."""
    return _invoke(
        lambda: _read_group(
            model,
            domain=domain or [],
            fields=fields,
            groupby=groupby,
            lazy=lazy,
        )
    )


@tool
def name_search(
    model: str,
    name: str = "",
    domain: Optional[list] = None,
    operator: str = "ilike",
    limit: int = 0,
) -> str:
    """Resolve a business name to (id, display_name) pairs. Not a substitute for search."""
    return _invoke(
        lambda: _name_search(
            model,
            name=name,
            domain=domain or [],
            operator=operator,
            limit=limit or None,
        )
    )


TYPED_ORM_LANGCHAIN_TOOLS: list[Any] = [
    fields_get,
    search,
    read,
    search_read,
    search_count,
    read_group,
    name_search,
]
