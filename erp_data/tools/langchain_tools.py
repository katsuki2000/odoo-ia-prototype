"""LangChain @tool wrappers over typed P9 ORM runtime reads."""

from __future__ import annotations

import ast
import json
from copy import deepcopy
from typing import Annotated, Any, Optional

from langchain_core.tools import tool
from pydantic import BeforeValidator, Field

from config import settings
from core.evidence import record_evidence
from erp_data.runtime.errors import OrmRuntimeError, SchemaNotReadError
from erp_data.tools.read_tools import (
    orm_fields_get as _fields_get,
    orm_list_models as _list_models,
    orm_name_search as _name_search,
    orm_read as _read,
    orm_read_group as _read_group,
    orm_search as _search,
    orm_search_count as _search_count,
    orm_search_read as _search_read,
)
from erp_data.runtime.types import OrmToolResult
from erp_data.runtime.validation import DOMAIN_LEAF_OPS, DOMAIN_LOGICAL_OPS

UNKNOWN_FIELDS_HINT = (
    "\nSome requested names are not fields of this model. Read the full list (fields_get without "
    "field_names) before concluding that a field does not exist."
)
NO_MODEL_HINT = (
    "\nNo model matches this keyword. Technical model names are in English and labels follow the "
    "interface language of the instance: try the English equivalent and a shorter root word of the term. "
    "The concept may also be a field of the model the question names: read that model's fields. "
    "If none of these finds it, the concept is not available to the requester: say so."
)
FULL_LIST_HINT = (
    "\nMatch every qualifier of the question (type, status, party, period) to a field of this list "
    "and apply each one as a filter or grouping."
)


def _parse_sequence(text: str) -> Optional[list]:
    for load in (ast.literal_eval, json.loads):
        try:
            parsed = load(text)
        except (ValueError, SyntaxError):
            continue
        if isinstance(parsed, (list, tuple)):
            return list(parsed)
    return None


def _coerce_list(value: Any) -> Any:
    """Small models often send a list argument as a string ('state' or "['a', 'b']").
    Turn those into a real list so the tool schema accepts them; leave anything else untouched."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    if text.startswith(("[", "(")):
        parsed = _parse_sequence(text)
        if parsed is not None:
            return parsed
    return [part.strip().strip("'\"") for part in text.split(",") if part.strip()]


LooseStrList = Annotated[Optional[list[str]], BeforeValidator(_coerce_list)]
DomainToken = str | tuple[str, str, Any]
def _is_domain_leaf(value: Any) -> bool:
    return isinstance(value, (list, tuple)) and len(value) == 3 and all(
        isinstance(value[index], str) for index in (0, 1)
    )


def _group_flat_leaves(items: list) -> list:
    """Small models also write a leaf as three consecutive items: 'state', '=', 'draft'."""
    grouped, index = [], 0
    while index < len(items):
        item = items[index]
        is_flat_leaf = (
            isinstance(item, str)
            and item not in DOMAIN_LOGICAL_OPS
            and index + 2 < len(items)
            and isinstance(items[index + 1], str)
            and items[index + 1] in DOMAIN_LEAF_OPS
        )
        grouped.append(items[index:index + 3] if is_flat_leaf else item)
        index += 3 if is_flat_leaf else 1
    return grouped


def _flatten_domain_tokens(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        parsed = _parse_sequence(text) if text.startswith(("[", "(")) else None
        return [value] if parsed is None else _flatten_domain_tokens(parsed)
    if _is_domain_leaf(value):
        return [value]
    if isinstance(value, list):
        return [token for item in _group_flat_leaves(value) for token in _flatten_domain_tokens(item)]
    return [value]


def _coerce_domain(value: Any) -> Any:
    value = _coerce_list(value)
    return _flatten_domain_tokens(value) if isinstance(value, list) else value


ModelName = Annotated[
    str, Field(description="Technical name of the Odoo model, always required (for example account.move).")
]
LooseDomain = Annotated[
    Optional[list[DomainToken]],
    BeforeValidator(_coerce_domain),
    Field(description='Odoo domain: a list of [field, operator, value] triplets and logical operators.'),
]


def _schema_hint(result: OrmToolResult) -> str:
    if result.observation.tool == "list_models":
        return "" if result.observation.row_count else NO_MODEL_HINT
    if result.observation.tool != "fields_get":
        return ""
    if result.evidence and result.evidence[0].value.get("unknown_fields"):
        return UNKNOWN_FIELDS_HINT
    return "" if result.observation.request["field_names"] else FULL_LIST_HINT


def _dumps(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))


def _format_observation(result: OrmToolResult) -> str:
    payload = {
        "tool": result.observation.tool,
        "model": result.observation.model,
        "row_count": result.observation.row_count,
        "truncated": result.observation.truncated,
        "value": deepcopy(result.evidence[0].value) if result.evidence else None,
    }
    limit = (
        settings.ORM_FIELDS_INDEX_MAX_CHARS if result.observation.tool == "fields_get"
        else settings.ORM_OBSERVATION_MAX_CHARS
    )
    body = _dumps(payload)
    output_truncated = len(body) > limit
    if output_truncated:
        payload["display_truncated"] = True
        value = payload.get("value")
        if isinstance(value, dict) and isinstance(value.get("fields"), dict):
            fields = value["fields"]
            while fields and len(_dumps(payload)) > limit:
                fields.pop(next(reversed(fields)))
        elif isinstance(value, list):
            while value and len(_dumps(payload)) > limit:
                value.pop()
        body = _dumps(payload)
        if len(body) > limit:
            body = _dumps({
                "tool": result.observation.tool,
                "model": result.observation.model,
                "display_truncated": True,
                "value_summary": "Output too large to display; narrow fields or reduce the record limit.",
            })
    notice = (
        "\nDisplayed output is truncated; omitted fields or records are not evidence. "
        "Ask the user for a row limit or a narrower filter."
    ) if output_truncated else ""
    return f"{result.text}{notice}\n{body}{_schema_hint(result)}"


def _invoke(call, retry_schema=True) -> str:
    try:
        result = call()
    except SchemaNotReadError as exc:
        if not retry_schema:
            return f"ORM read refused: {exc}"
        try:
            schema = _fields_get(exc.model)
        except OrmRuntimeError as schema_error:
            return f"ORM read refused: {schema_error}"
        record_evidence(schema.evidence)
        return _invoke(call, retry_schema=False)
    except OrmRuntimeError as exc:
        return f"ORM read refused: {exc}"
    record_evidence(result.evidence)
    return _format_observation(result)


@tool
def fields_get(model: ModelName, field_names: LooseStrList = None) -> str:
    """List every field of an Odoo model as name -> type and label. Pass field_names to get the full
    details (relation, selection values) of those fields."""
    return _invoke(lambda: _fields_get(model, field_names))


@tool
def search(
    model: ModelName,
    domain: LooseDomain = None,
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
def read(model: ModelName, ids: list[int], fields: list[str]) -> str:
    """Read explicit fields for known record ids. fields must be non-empty."""
    return _invoke(lambda: _read(model, ids=ids, fields=fields))


@tool
def search_read(
    model: ModelName,
    domain: LooseDomain = None,
    fields: LooseStrList = None,
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
def search_count(
    model: ModelName,
    domain: LooseDomain = None,
) -> str:
    """Count records matching an Odoo domain (how many)."""
    return _invoke(lambda: _search_count(model, domain=domain or []))


@tool
def read_group(
    model: ModelName,
    fields: list[str],
    groupby: LooseStrList = None,
    domain: LooseDomain = None,
    lazy: bool = True,
) -> str:
    """Aggregate with read_group. fields may use aggregates like amount_total:sum; omit groupby for one total."""
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
    model: ModelName,
    name: str = "",
    domain: LooseDomain = None,
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


@tool
def list_models(query: str) -> str:
    """Find the technical name of an Odoo model from one keyword of its name or label (for example
    'property'). Use it only when the model name is unknown or was refused, not for a standard model you know.
    Lists only the models the requester may read, with their labels; prefer a business model to a report model."""
    return _invoke(lambda: _list_models(query))


TYPED_ORM_LANGCHAIN_TOOLS: list[Any] = [
    list_models,
    fields_get,
    search,
    read,
    search_read,
    search_count,
    read_group,
    name_search,
]
