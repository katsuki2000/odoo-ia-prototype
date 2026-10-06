"""Shared helpers so legacy domain tools reuse the typed ORM runtime."""

from __future__ import annotations

from typing import Any

from core.evidence.evidence import Evidence
from erp_data.runtime.types import OrmToolResult


def runtime_scope(result: OrmToolResult) -> dict[str, Any]:
    if result.evidence:
        return dict(result.evidence[0].scope)
    return {}


def runtime_records(result: OrmToolResult) -> list:
    value = result.evidence[0].value if result.evidence else None
    return value if isinstance(value, list) else []


def prepend_runtime_evidence(
    result: OrmToolResult, extras: list[Evidence]
) -> list[Evidence]:
    return list(result.evidence) + list(extras)
