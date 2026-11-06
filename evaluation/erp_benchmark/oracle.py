"""Runtime oracle for the value-free ERP query plans."""

from __future__ import annotations

import datetime as _datetime
import math
from dataclasses import dataclass
from typing import Any, Protocol

class ReadExecutor(Protocol):
    def execute(self, model: str, method: str, args: list[Any], kwargs: dict[str, Any] | None = None) -> Any:
        ...


class OracleError(RuntimeError):
    """Raised when a plan cannot be evaluated safely on the target instance."""


class NotApplicable(OracleError):
    """The instance does not provide enough applicable data for a case."""


@dataclass(frozen=True)
class OracleResult:
    status: str
    kind: str
    expected_groups: tuple[tuple[str, ...], ...] = ()
    row_groups: tuple[tuple[tuple[str, ...], ...], ...] = ()
    value: Any = None
    count: int | None = None
    rows: tuple[dict[str, Any], ...] = ()
    empty: bool = False
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "kind": self.kind,
            "expected_groups": [list(group) for group in self.expected_groups],
            "row_groups": [[list(group) for group in row] for row in self.row_groups],
            "value": self.value,
            "count": self.count,
            "rows": list(self.rows),
            "empty": self.empty,
            "reason": self.reason,
        }


def _today() -> str:
    return _datetime.date.today().isoformat()


def _resolve_tokens(value: Any, executor: ReadExecutor | None = None) -> Any:
    if isinstance(value, list):
        return [_resolve_tokens(item, executor) for item in value]
    if isinstance(value, dict):
        if value == {"$today": True}:
            return _today()
        if value == {"$active_company": True}:
            return getattr(executor, "active_company_id", None)
        return {key: _resolve_tokens(item, executor) for key, item in value.items()}
    return value


def _is_id_pair(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 2 and isinstance(value[0], int)


def _public_value(value: Any) -> Any:
    if _is_id_pair(value):
        return value[1]
    if isinstance(value, list):
        return [_public_value(item) for item in value if not isinstance(item, int)]
    return value


MONTHS = (
    ("January", "janvier"), ("February", "février"), ("March", "mars"), ("April", "avril"),
    ("May", "mai"), ("June", "juin"), ("July", "juillet"), ("August", "août"),
    ("September", "septembre"), ("October", "octobre"), ("November", "novembre"), ("December", "décembre"),
)


def _number_variants(value: int | float) -> tuple[str, ...]:
    if isinstance(value, bool) or not math.isfinite(float(value)):
        return (str(value),)
    raw = str(value)
    fixed = f"{value:.2f}"
    variants = {raw, raw.replace(".", ","), fixed, fixed.replace(".", ",")}
    if fixed.endswith(".00"):
        variants.update({fixed[:-3], fixed[:-3].replace(".", ",")})
    return tuple(sorted(variants))


def _date_variants(value: str) -> tuple[str, ...]:
    if len(value) >= 10:
        date_part = value[:10]
        try:
            parsed = _datetime.date.fromisoformat(date_part)
        except ValueError:
            return (value,)
        month = MONTHS[parsed.month - 1][1]
        return (value, date_part, parsed.strftime("%d/%m/%Y"), f"{parsed.day} {month} {parsed.year}", f"{parsed.day:02d} {month} {parsed.year}")
    return (value,)


def _label_variants(label: str) -> tuple[str, ...]:
    """A selection label, plus its French form when it is an English month name."""
    return (label, *(french for english, french in MONTHS if english == label))


def _fact_variants(value: Any, labels: dict[str, str] | None = None) -> tuple[str, ...]:
    value = _public_value(value)
    if value is None or value == "":
        return ()
    if isinstance(value, bool):
        return ("true", "false") if value else ("false", "non", "no")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _number_variants(value)
    if isinstance(value, str):
        variants = _date_variants(value) if len(value) >= 10 and value[4] == "-" else (value,)
        label = (labels or {}).get(value)
        return tuple(dict.fromkeys((*variants, *_label_variants(label)))) if label else variants
    return (str(value),)


def _selection_labels(metadata: dict[str, dict[str, Any]]) -> dict[str, dict[str, str]]:
    return {field: dict(info["selection"]) for field, info in metadata.items() if info.get("type") == "selection"}


def _field_metadata(executor: ReadExecutor, model: str, fields: list[str]) -> dict[str, dict[str, Any]]:
    result = executor.execute(
        model,
        "fields_get",
        [fields],
        {"attributes": ["string", "type", "relation", "selection"]},
    )
    if not isinstance(result, dict):
        raise OracleError(f"fields_get returned no metadata for {model}")
    missing = sorted(set(fields) - result.keys())
    if missing:
        raise NotApplicable(f"fields unavailable on {model}: {missing}")
    return result


def _read_rows(
    executor: ReadExecutor,
    model: str,
    domain: list[list[Any]],
    fields: list[str],
    max_rows: int,
) -> list[dict[str, Any]]:
    rows = executor.execute(
        model,
        "search_read",
        [domain],
        {"fields": fields, "limit": max_rows + 1, "order": "id"},
    )
    if len(rows) > max_rows:
        raise NotApplicable(f"result has more than the {max_rows}-row evaluation limit")
    return rows


def _related_ids(value: Any) -> list[int]:
    if _is_id_pair(value):
        return [value[0]]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, int)]
    return []


def _expand_relations(
    executor: ReadExecutor,
    rows: list[dict[str, Any]],
    metadata: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    expanded = [dict(row) for row in rows]
    cache: dict[tuple[str, tuple[int, ...]], dict[int, dict[str, Any]]] = {}
    for field, info in metadata.items():
        relation = info.get("relation")
        if not relation or info.get("type") not in {"many2many", "one2many"}:
            continue
        ids = sorted({item for row in rows for item in _related_ids(row.get(field))})
        if not ids:
            continue
        key = (relation, tuple(ids))
        related = cache.get(key)
        if related is None:
            related_rows = executor.execute(relation, "read", [ids], {"fields": ["display_name", "name"]})
            related = {int(item["id"]): item for item in related_rows}
            cache[key] = related
        for row in expanded:
            row[field] = [related[item].get("display_name") or related[item].get("name") for item in _related_ids(row.get(field)) if item in related]
    return expanded


def _row_public_values(
    executor: ReadExecutor, rows: list[dict[str, Any]], metadata: dict[str, dict[str, Any]], fields: list[str]
) -> list[dict[str, Any]]:
    expanded = _expand_relations(executor, rows, metadata)
    return [{field: _public_value(row.get(field)) for field in fields} for row in expanded]


def _groups_for_row(row: dict[str, Any], labels: dict[str, dict[str, str]] | None = None) -> tuple[tuple[str, ...], ...]:
    labels = labels or {}
    return tuple(group for field, value in row.items() for group in (_fact_variants(value, labels.get(field)),) if group)


def _result_for_rows(executor: ReadExecutor, plan: dict[str, Any], max_rows: int) -> OracleResult:
    fields = list(plan["fields"])
    raw_rows = _read_rows(executor, plan["model"], _resolve_tokens(plan["domain"], executor), fields, max_rows)
    metadata = _field_metadata(executor, plan["model"], fields)
    public_rows = _row_public_values(executor, raw_rows, metadata, fields)
    labels = _selection_labels(metadata)
    row_groups = tuple(_groups_for_row(row, labels) for row in public_rows)
    expected = tuple(group for row in row_groups for group in row)
    return OracleResult(
        status="ok",
        kind=plan["kind"],
        expected_groups=expected,
        row_groups=row_groups,
        count=len(public_rows),
        rows=tuple(public_rows),
        empty=not public_rows,
    )


def _result_for_count(executor: ReadExecutor, plan: dict[str, Any]) -> OracleResult:
    count = int(executor.execute(plan["model"], "search_count", [_resolve_tokens(plan["domain"], executor)], {}))
    return OracleResult(
        status="ok",
        kind=plan["kind"],
        expected_groups=((str(count),),),
        count=count,
        value=count,
        empty=count == 0,
    )


def _result_for_aggregate(executor: ReadExecutor, plan: dict[str, Any], max_rows: int) -> OracleResult:
    fields = [plan["field"]]
    currency_field = plan.get("currency_field")
    if currency_field:
        fields.append(currency_field)
    raw_rows = _read_rows(executor, plan["model"], _resolve_tokens(plan["domain"], executor), fields, max_rows)
    totals: dict[str, dict[str, Any]] = {}
    for row in raw_rows:
        value = row.get(plan["field"])
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        currency = _public_value(row.get(currency_field)) if currency_field else ""
        bucket = totals.setdefault(str(currency), {"currency": currency, "total": 0.0})
        bucket["total"] += value
    if not totals:
        totals[""] = {"currency": "", "total": 0.0}
    return OracleResult(
        status="ok",
        kind=plan["kind"],
        expected_groups=tuple(_fact_variants(bucket["total"]) for bucket in totals.values()),
        value=[dict(item) for item in totals.values()],
        count=len(raw_rows),
        empty=not raw_rows,
    )


def _follow_path(executor: ReadExecutor, root: dict[str, Any], paths: list[dict[str, Any]], max_rows: int) -> list[dict[str, Any]]:
    records = [root]
    for index, step in enumerate(paths):
        ids = sorted({item for record in records for item in _related_ids(record.get(step["field"]))})
        if not ids:
            return []
        fields = list(step["fields"])
        if index + 1 < len(paths):
            next_field = paths[index + 1]["field"]
            if next_field not in fields:
                fields.append(next_field)
        records = executor.execute(step["model"], "read", [ids], {"fields": fields})
        if len(records) > max_rows:
            raise NotApplicable(f"relation has more than the {max_rows}-row evaluation limit")
    return records


def _result_for_relation(executor: ReadExecutor, plan: dict[str, Any], max_rows: int) -> OracleResult:
    fields = list(plan["fields"])
    raw_rows = _read_rows(executor, plan["model"], _resolve_tokens(plan["domain"], executor), fields, max_rows)
    output_rows = []
    row_groups = []
    has_related = False
    for root in raw_rows:
        root_relation_fields = {chain[0]["field"] for chain in plan["paths"]}
        public_root = {field: _public_value(root.get(field)) for field in fields if field not in root_relation_fields}
        public = dict(public_root)
        groups = list(_groups_for_row(public_root))
        for index, chain in enumerate(plan["paths"]):
            related = _follow_path(executor, root, chain, max_rows)
            values = []
            for record in related:
                value = {field: _public_value(record.get(field)) for field in chain[-1]["fields"]}
                values.append(value)
                groups.extend(_groups_for_row(value))
            has_related = has_related or bool(values)
            public[f"relation_{index + 1}"] = values
        output_rows.append(public)
        row_groups.append(tuple(groups))
    expected = tuple(group for row in row_groups for group in row)
    return OracleResult(
        status="ok",
        kind=plan["kind"],
        expected_groups=expected,
        row_groups=tuple(row_groups),
        count=len(output_rows),
        rows=tuple(output_rows),
        empty=not has_related,
    )


def _result_for_value(executor: ReadExecutor, plan: dict[str, Any]) -> OracleResult:
    rows = _read_rows(executor, plan["model"], _resolve_tokens(plan["domain"], executor), [plan["field"]], 1)
    if not rows:
        raise NotApplicable(f"no record found for {plan['model']}")
    raw = rows[0].get(plan["field"])
    public = _public_value(raw)
    metadata = _field_metadata(executor, plan["model"], [plan["field"]])
    groups = _fact_variants(public, _selection_labels(metadata).get(plan["field"]))
    return OracleResult(status="ok", kind=plan["kind"], expected_groups=(groups,), value=public)


def evaluate_plan(executor: ReadExecutor, plan: dict[str, Any], max_rows: int = 50) -> OracleResult:
    """Evaluate one plan through read-only ORM methods."""
    try:
        kind = plan["kind"]
        if kind == "count":
            return _result_for_count(executor, plan)
        if kind == "aggregate":
            return _result_for_aggregate(executor, plan, max_rows)
        if kind == "rows":
            return _result_for_rows(executor, plan, max_rows)
        if kind == "relation":
            return _result_for_relation(executor, plan, max_rows)
        if kind == "value":
            return _result_for_value(executor, plan)
    except NotApplicable:
        raise
    except Exception as error:
        raise NotApplicable(str(error)) from error
    raise OracleError(f"unknown oracle plan kind: {plan.get('kind')!r}")
