"""Orchestrate the frozen cases over the evaluation instances and score the saved raw responses."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import asdict, replace
from pathlib import Path
from typing import Iterable, Mapping, Optional

from core.evaluation import instances as ib
from core.evaluation.case_worker import read_raw
from core.evaluation.frozen_cases import FrozenDataset, require, split_cases
from core.evaluation.instance_runtime import (
    free_port,
    provision_credentials,
    serve_instance,
    worker_environment,
)
from core.evaluation.system_adapter import to_case_result

RUN_FILE = "run.json"
MAX_CASE_BATCH_SIZE = 2


def select_cases(dataset: FrozenDataset, case_ids: Iterable[str]) -> FrozenDataset:
    requested = list(case_ids)
    require(0 < len(requested) <= MAX_CASE_BATCH_SIZE,
            f"case batch must contain between 1 and {MAX_CASE_BATCH_SIZE} ids")
    require(len(set(requested)) == len(requested), "case batch contains duplicate ids")
    known = {case.case_id for case in dataset.cases}
    unknown = sorted(set(requested) - known)
    require(not unknown, f"unknown case ids: {unknown}")
    selected = set(requested)
    return replace(dataset, cases=tuple(case for case in dataset.cases if case.case_id in selected))


def cases_by_instance(dataset: FrozenDataset) -> dict:
    groups: dict = {}
    for case in dataset.cases:
        groups.setdefault(case.instance, []).append(case)
    return groups


def prepare_run(dataset: FrozenDataset, raw_dir: Path) -> None:
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    marker = raw_dir / RUN_FILE
    if marker.is_file():
        recorded = json.loads(marker.read_text(encoding="utf-8"))["dataset_digest"]
        require(recorded == dataset.digest, "raw directory belongs to another dataset version")
    marker.write_text(json.dumps({"dataset_digest": dataset.digest}), encoding="utf-8")


def run_instance(
    spec: ib.InstanceSpec, cases: Iterable, env: ib.BuildEnvironment, raw_path: Path, project_root: Path,
) -> None:
    cases = list(cases)
    users = sorted({case.user_context.user for case in cases})
    credentials = provision_credentials(spec, env, users)
    with serve_instance(spec, env, free_port()) as base_url, tempfile.TemporaryDirectory() as workdir:
        cases_file = Path(workdir) / "cases.json"
        credentials_file = Path(workdir) / "credentials.json"
        cases_file.write_text(json.dumps([asdict(case) for case in cases]), encoding="utf-8")
        credentials_file.write_text(json.dumps(credentials), encoding="utf-8")
        credentials_file.chmod(0o600)
        result = subprocess.run(
            [sys.executable, "-m", "core.evaluation.case_worker",
             "--cases", str(cases_file), "--credentials", str(credentials_file), "--output", str(raw_path)],
            cwd=project_root,
            env=worker_environment(spec, env, base_url),
            check=False,
        )
    require(result.returncode == 0, f"worker failed for instance {spec.name} (exit {result.returncode})")


def run_protocol(
    dataset: FrozenDataset,
    specs: Iterable[ib.InstanceSpec],
    env: ib.BuildEnvironment,
    raw_dir: Path,
    project_root: Path,
    only: Optional[Iterable[str]] = None,
) -> list:
    prepare_run(dataset, raw_dir)
    by_instance = cases_by_instance(dataset)
    failures = []
    for spec in specs:
        if spec.name not in by_instance or (only is not None and spec.name not in only):
            continue
        try:
            run_instance(spec, by_instance[spec.name], env, Path(raw_dir) / f"{spec.name}.jsonl", project_root)
        except (RuntimeError, ValueError, FileNotFoundError, TimeoutError) as error:
            failures.append({"name": spec.name, "error": str(error)})
    return failures


def collect_results(dataset: FrozenDataset, raw_dir: Path) -> list:
    marker = Path(raw_dir) / RUN_FILE
    require(marker.is_file(), "no run recorded in the raw directory")
    require(
        json.loads(marker.read_text(encoding="utf-8"))["dataset_digest"] == dataset.digest,
        "raw directory belongs to another dataset version",
    )
    by_id = {case.case_id: case for case in dataset.cases}
    results = []
    for path in sorted(Path(raw_dir).glob("*.jsonl")):
        for row in read_raw(path).values():
            case = by_id.get(row["case_id"])
            if case is not None:
                results.append(to_case_result(case, row["raw"]))
    return results


def load_ratings(path: Optional[Path]) -> Optional[Mapping[str, bool]]:
    if path is None:
        return None
    return {key: bool(value) for key, value in json.loads(Path(path).read_text(encoding="utf-8")).items()}


def split_summary(dataset: FrozenDataset) -> dict:
    return {split: len(split_cases(dataset, split)) for split in ("calibration", "held_out")}
