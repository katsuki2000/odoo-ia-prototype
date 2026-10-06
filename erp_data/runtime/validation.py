import re
from typing import Any, Optional

from config import settings
from erp_data.runtime.errors import OrmRuntimeError

_MODEL_NAME_RE = re.compile(r"^[a-z][a-z0-9_.]*$")
_DOMAIN_OPS = frozenset({"&", "|", "!"})
_FIELD_NAME_RE = re.compile(r"^[a-z0-9_.]+(:[a-z]+)?$", re.IGNORECASE)


def cap_row_limit(limit: Optional[int]) -> int:
    ceiling = settings.ORM_RUNTIME_MAX_ROWS
    if limit is None or limit <= 0:
        return ceiling
    return min(int(limit), ceiling)


def cap_name_search_limit(limit: Optional[int]) -> int:
    ceiling = settings.ORM_NAME_SEARCH_LIMIT
    if limit is None or limit <= 0:
        return ceiling
    return min(int(limit), ceiling)


def validate_model_name(model: str) -> str:
    if not isinstance(model, str) or not _MODEL_NAME_RE.match(model):
        raise OrmRuntimeError(f"invalid model name: {model!r}")
    return model


def validate_domain(domain: Any) -> list:
    if domain is None:
        return []
    if not isinstance(domain, list):
        raise OrmRuntimeError("domain must be a list")
    for item in domain:
        if isinstance(item, str):
            if item not in _DOMAIN_OPS:
                raise OrmRuntimeError(f"invalid domain operator: {item!r}")
            continue
        if isinstance(item, (list, tuple)):
            if len(item) != 3:
                raise OrmRuntimeError("domain leaf must be a 3-tuple")
            field, _op, _val = item
            if not isinstance(field, str):
                raise OrmRuntimeError("domain field must be a string")
            continue
        raise OrmRuntimeError(f"invalid domain entry: {item!r}")
    return domain


def validate_field_list(fields: Any, *, allow_aggregate: bool = False) -> list[str]:
    if fields is None:
        return []
    if not isinstance(fields, list) or not fields:
        raise OrmRuntimeError("fields must be a non-empty list of strings")
    out: list[str] = []
    for name in fields:
        if not isinstance(name, str):
            raise OrmRuntimeError("each field name must be a string")
        if not _FIELD_NAME_RE.match(name):
            raise OrmRuntimeError(f"invalid field name: {name!r}")
        if not allow_aggregate and ":" in name:
            raise OrmRuntimeError(f"aggregate field not allowed here: {name!r}")
        out.append(name)
    return out


def validate_record_ids(ids: Any, *, max_rows: int) -> list[int]:
    if not isinstance(ids, list) or not ids:
        raise OrmRuntimeError("ids must be a non-empty list of integers")
    if len(ids) > max_rows:
        raise OrmRuntimeError(f"too many record ids (max {max_rows})")
    out: list[int] = []
    for item in ids:
        if not isinstance(item, int) or item <= 0:
            raise OrmRuntimeError("each id must be a positive integer")
        out.append(item)
    return out


def validate_groupby(groupby: Any) -> list[str]:
    if not isinstance(groupby, list) or not groupby:
        raise OrmRuntimeError("groupby must be a non-empty list of strings")
    for name in groupby:
        if not isinstance(name, str) or not name:
            raise OrmRuntimeError("each groupby entry must be a non-empty string")
    return groupby


def _company_values(value: Any) -> list[int]:
    if isinstance(value, bool):
        return []
    if isinstance(value, int):
        return [value]
    if isinstance(value, (list, tuple)):
        out: list[int] = []
        for item in value:
            if isinstance(item, bool):
                continue
            if isinstance(item, int):
                out.append(item)
        return out
    return []


def assert_domain_within_companies(
    domain: list, allowed_company_ids: Optional[list[int]]
) -> None:
    """Refuse domain leaves that target a company outside the session scope."""
    if not allowed_company_ids:
        return
    allowed = set(int(x) for x in allowed_company_ids)
    for item in domain:
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            continue
        field, op, val = item
        if not isinstance(field, str):
            continue
        if field != "company_id" and not field.endswith(".company_id"):
            continue
        if op == "=":
            values = _company_values(val)
            if values and values[0] not in allowed:
                raise OrmRuntimeError(
                    f"domain company_id={values[0]} outside allowed companies {sorted(allowed)}"
                )
        elif op == "in":
            values = _company_values(val)
            outside = [v for v in values if v not in allowed]
            if outside:
                raise OrmRuntimeError(
                    f"domain company_id in {values} outside allowed companies {sorted(allowed)}"
                )
