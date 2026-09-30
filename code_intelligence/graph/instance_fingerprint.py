"""Build reproducible fingerprints for an Odoo instance and its source paths."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional


@dataclass(frozen=True)
class InstanceFingerprint:
    modules: tuple[tuple[str, str, str], ...]
    source_modules: tuple[tuple[str, str], ...]
    addon_paths: tuple[str, ...]
    active_languages: tuple[str, ...]
    request_language: Optional[str]
    source_availability: tuple[tuple[str, bool], ...]
    runtime_inventory_available: bool
    language_inventory_available: bool
    digest: str

    def to_dict(self) -> dict:
        return asdict(self)


def build_instance_fingerprint(
    installed_modules: Optional[Iterable[Mapping[str, object]]],
    addon_paths: Iterable[str | Path],
    active_languages: Optional[Iterable[str]],
    request_language: Optional[str],
    source_modules: Optional[Mapping[str, str]] = None,
) -> InstanceFingerprint:
    """Hash installed module state, configured paths, and language context.

    Passing ``None`` for a runtime-derived value records that it is unknown.
    Module rows accept Odoo's ``name``, ``installed_version`` and ``state``.
    """
    modules = tuple(sorted(
        (
            str(row.get("name", "")),
            str(row.get("installed_version") or row.get("latest_version") or ""),
            str(row.get("state", "")),
        )
        for row in (installed_modules or ())
        if row.get("name")
    ))
    paths = tuple(sorted({str(Path(path).expanduser().resolve()) for path in addon_paths}))
    languages = tuple(sorted(set(active_languages or ())))
    source_module_rows = tuple(sorted((source_modules or {}).items()))
    source_availability = tuple(sorted((path, Path(path).is_dir()) for path in paths))
    canonical = {
        "modules": modules if installed_modules is not None else None,
        "source_modules": source_module_rows,
        "addon_paths": paths,
        "active_languages": languages if active_languages is not None else None,
        "request_language": request_language,
        "source_availability": source_availability,
        "runtime_inventory_available": installed_modules is not None,
        "language_inventory_available": active_languages is not None,
    }
    digest = hashlib.sha256(json.dumps(
        canonical,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return InstanceFingerprint(
        modules=modules,
        source_modules=source_module_rows,
        addon_paths=paths,
        active_languages=languages,
        request_language=request_language,
        source_availability=source_availability,
        runtime_inventory_available=installed_modules is not None,
        language_inventory_available=active_languages is not None,
        digest=digest,
    )


def read_runtime_inventory(connector, uid: int, language_reader=None) -> tuple[list[dict], Optional[list[str]]]:
    """Read installed module versions and active languages via injected connector.

    Connector permissions remain the caller's responsibility; unsupported
    models or unavailable runtime access produce an explicit empty inventory.
    """
    modules = connector.search_read(
        uid=uid,
        model="ir.module.module",
        domain=[("state", "=", "installed")],
        fields=["name", "installed_version", "latest_version", "state"],
        limit=0,
    )
    if language_reader is None:
        languages = None
    else:
        languages = language_reader(uid)
        languages = sorted(set(languages)) if languages is not None else None
    return modules, languages


__all__ = ["InstanceFingerprint", "build_instance_fingerprint", "read_runtime_inventory"]
