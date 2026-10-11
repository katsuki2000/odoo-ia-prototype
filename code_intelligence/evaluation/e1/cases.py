"""Calibration set C for E1 (distinct from frozen_cases held_out)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

DATA_DIR = Path(__file__).resolve().parent / "data"
CASES_PATH = DATA_DIR / "calibration_cases.json"

FAMILIES = frozenset(
    {"paraphrase", "exact_label", "non_model", "ambiguous", "absent", "bilingual_pair"}
)
ABSTENTION_RULES = frozenset({"none", "must_clarify"})
OBJECT_REF = re.compile(r"^(model|menu|field|method|rule|group):.+$")
CASE_ID = re.compile(r"^[a-z0-9_]+$")


@dataclass(frozen=True)
class E1Case:
    case_id: str
    family: str
    instance: str
    language: str
    module: str
    question: str
    expected_objects: tuple[str, ...]
    abstention_rule: str
    ground_truth: Mapping[str, str]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "E1Case":
        case = cls(
            case_id=str(data["case_id"]),
            family=str(data["family"]),
            instance=str(data["instance"]),
            language=str(data["language"]),
            module=str(data["module"]),
            question=str(data["question"]),
            expected_objects=tuple(data.get("expected_objects") or ()),
            abstention_rule=str(data["abstention_rule"]),
            ground_truth=dict(data["ground_truth"]),
        )
        case.validate()
        return case

    def validate(self) -> None:
        if CASE_ID.match(self.case_id) is None:
            raise ValueError(f"invalid case_id: {self.case_id}")
        if self.family not in FAMILIES:
            raise ValueError(f"{self.case_id}: unknown family {self.family}")
        if self.abstention_rule not in ABSTENTION_RULES:
            raise ValueError(f"{self.case_id}: bad abstention_rule")
        if not self.question.strip():
            raise ValueError(f"{self.case_id}: empty question")
        if not all(OBJECT_REF.match(ref) for ref in self.expected_objects):
            raise ValueError(f"{self.case_id}: invalid expected_objects")
        if self.abstention_rule == "none" and not self.expected_objects:
            raise ValueError(f"{self.case_id}: expected_objects required")
        method = self.ground_truth.get("method", "")
        if method not in {"human_review", "odoo_oracle"}:
            raise ValueError(f"{self.case_id}: ground_truth.method must be human_review or odoo_oracle")


def dataset_digest(cases: Iterable[E1Case]) -> str:
    rows = [
        {
            "case_id": case.case_id,
            "family": case.family,
            "instance": case.instance,
            "language": case.language,
            "module": case.module,
            "question": case.question,
            "expected_objects": list(case.expected_objects),
            "abstention_rule": case.abstention_rule,
            "ground_truth": dict(case.ground_truth),
        }
        for case in cases
    ]
    rows.sort(key=lambda row: row["case_id"])
    canonical = json.dumps(rows, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_calibration_cases(path: Path | None = None) -> tuple[tuple[E1Case, ...], str, dict[str, Any]]:
    cases_path = path or CASES_PATH
    payload = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = tuple(sorted(
        (E1Case.from_dict(row) for row in payload.get("cases", [])),
        key=lambda case: case.case_id,
    ))
    ids = [case.case_id for case in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate case ids in E1 calibration set")
    digest = dataset_digest(cases)
    meta = {
        "version": payload.get("version"),
        "status": payload.get("status"),
        "split": payload.get("split"),
        "notes": payload.get("notes"),
        "path": str(cases_path),
        "digest": digest,
        "count": len(cases),
    }
    return cases, digest, meta
