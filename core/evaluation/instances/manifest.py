"""Instance manifest merging and persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping


def merge_manifests(existing: Mapping, new: Mapping) -> dict:
    rebuilt = {row["name"] for row in new["instances"]} | {row["name"] for row in new["failures"]}
    instances = [row for row in existing.get("instances", []) if row["name"] not in rebuilt] + list(new["instances"])
    failures = [row for row in existing.get("failures", []) if row["name"] not in rebuilt] + list(new["failures"])
    return {
        "instances": sorted(instances, key=lambda row: row["name"]),
        "failures": sorted(failures, key=lambda row: row["name"]),
    }


def write_manifest(manifest: Mapping, output_dir: Path) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "manifest.json"
    if target.is_file():
        manifest = merge_manifests(json.loads(target.read_text(encoding="utf-8")), manifest)
    target.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return target
