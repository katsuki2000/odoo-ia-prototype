"""Schema, validation and freezing of the frozen evaluation cases."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping

from code_intelligence.agent.investigation_schemas import QuestionIntent
from core.evaluation.instances import SPLITS, InstanceSpec

SOURCES = ("runtime", "code", "internal_docs", "odoo_docs")
EVIDENCE_KINDS = ("graph", "orm", "document")
ABSTENTION_RULES = ("none", "must_clarify", "must_refuse_unauthorized")
GROUND_TRUTH_METHODS = ("odoo_oracle", "human_review", "documentation")
CASE_ID = re.compile(r"^[a-z0-9_]+$")
XML_ID = re.compile(r"^[a-z0-9_]+\.[A-Za-z0-9_.]+$")
LANGUAGE = re.compile(r"^[a-z]{2}_[A-Z]{2}$")
OBJECT_REF = re.compile(r"^(model|field|view|group|rule|menu|action|method|module):\S+$")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def clean_strings(values: Iterable, label: str) -> tuple:
    result = tuple(values)
    require(all(isinstance(value, str) and value.strip() for value in result), f"{label}: non-empty strings required")
    return result


@dataclass(frozen=True)
class UserContext:
    user: str
    company: str
    language: str
    groups: tuple = ()

    @classmethod
    def from_dict(cls, data: Mapping) -> "UserContext":
        context = cls(data["user"], data["company"], data["language"], clean_strings(data.get("groups", ()), "groups"))
        require(XML_ID.match(context.user) is not None, f"user must be an external id: {context.user}")
        require(XML_ID.match(context.company) is not None, f"company must be an external id: {context.company}")
        require(LANGUAGE.match(context.language) is not None, f"invalid language: {context.language}")
        require(all(XML_ID.match(group) for group in context.groups), "groups must be external ids")
        return context


@dataclass(frozen=True)
class EvidenceSpec:
    kind: str
    source: str

    @classmethod
    def from_dict(cls, data: Mapping) -> "EvidenceSpec":
        spec = cls(data["kind"], data["source"])
        require(spec.kind in EVIDENCE_KINDS, f"evidence kind must be one of {EVIDENCE_KINDS}")
        require(bool(spec.source.strip()), "evidence source required")
        return spec


@dataclass(frozen=True)
class ExpectedClaim:
    claim_id: str
    statement: str
    all_of: tuple = ()
    any_of: tuple = ()
    none_of: tuple = ()

    @classmethod
    def from_dict(cls, data: Mapping) -> "ExpectedClaim":
        claim = cls(
            data["claim_id"],
            data["statement"],
            clean_strings(data.get("all_of", ()), "all_of"),
            tuple(clean_strings(group, "any_of") for group in data.get("any_of", ())),
            clean_strings(data.get("none_of", ()), "none_of"),
        )
        require(bool(claim.statement.strip()), f"{claim.claim_id}: statement required")
        require(
            bool(claim.all_of) or any(claim.any_of),
            f"{claim.claim_id}: at least one matching term required",
        )
        require(all(claim.any_of), f"{claim.claim_id}: empty any_of group")
        return claim


@dataclass(frozen=True)
class GroundTruth:
    author: str
    method: str
    reference: str = ""

    @classmethod
    def from_dict(cls, data: Mapping) -> "GroundTruth":
        truth = cls(data["author"], data["method"], data.get("reference", ""))
        require(bool(truth.author.strip()), "ground truth author required")
        require(truth.method in GROUND_TRUTH_METHODS, f"ground truth method must be one of {GROUND_TRUTH_METHODS}")
        return truth


@dataclass(frozen=True)
class FrozenCase:
    case_id: str
    split: str
    instance: str
    user_context: UserContext
    question: str
    module: str
    expected_intent: str
    expected_sources: tuple
    expected_objects: tuple
    acceptable_evidence: tuple
    expected_claims: tuple
    abstention_rule: str
    ground_truth: GroundTruth

    @classmethod
    def from_dict(cls, data: Mapping) -> "FrozenCase":
        case = cls(
            case_id=data["case_id"],
            split=data["split"],
            instance=data["instance"],
            user_context=UserContext.from_dict(data["user_context"]),
            question=data["question"],
            module=data["module"],
            expected_intent=data["expected_intent"],
            expected_sources=clean_strings(data["expected_sources"], "expected_sources"),
            expected_objects=clean_strings(data.get("expected_objects", ()), "expected_objects"),
            acceptable_evidence=tuple(EvidenceSpec.from_dict(row) for row in data.get("acceptable_evidence", ())),
            expected_claims=tuple(ExpectedClaim.from_dict(row) for row in data.get("expected_claims", ())),
            abstention_rule=data["abstention_rule"],
            ground_truth=GroundTruth.from_dict(data["ground_truth"]),
        )
        case.validate()
        return case

    def validate(self) -> None:
        label = self.case_id
        require(CASE_ID.match(self.case_id) is not None, f"invalid case_id: {label}")
        require(self.split in SPLITS, f"{label}: split must be one of {SPLITS}")
        require(bool(self.instance.strip()) and bool(self.module.strip()), f"{label}: instance and module required")
        require(bool(self.question.strip()), f"{label}: question required")
        require(self.expected_intent in {intent.value for intent in QuestionIntent}, f"{label}: unknown intent")
        require(
            bool(self.expected_sources) and set(self.expected_sources) <= set(SOURCES),
            f"{label}: expected_sources must be a non-empty subset of {SOURCES}",
        )
        require(all(OBJECT_REF.match(ref) for ref in self.expected_objects), f"{label}: invalid object reference")
        require(self.abstention_rule in ABSTENTION_RULES, f"{label}: abstention_rule must be one of {ABSTENTION_RULES}")
        claim_ids = [claim.claim_id for claim in self.expected_claims]
        require(len(set(claim_ids)) == len(claim_ids), f"{label}: duplicate claim ids")
        if self.abstention_rule == "none":
            require(bool(self.expected_claims), f"{label}: expected_claims required when no abstention is expected")
            require(bool(self.acceptable_evidence), f"{label}: acceptable_evidence required")


@dataclass(frozen=True)
class FrozenDataset:
    version: int
    digest: str
    cases: tuple


def dataset_digest(cases: Iterable) -> str:
    rows = sorted((asdict(case) if isinstance(case, FrozenCase) else dict(case) for case in cases), key=lambda row: row["case_id"])
    canonical = json.dumps(rows, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_cases(rows: Iterable[Mapping]) -> tuple:
    cases = tuple(FrozenCase.from_dict(row) for row in rows)
    ids = [case.case_id for case in cases]
    require(len(set(ids)) == len(ids), "duplicate case ids in dataset")
    return tuple(sorted(cases, key=lambda case: case.case_id))


def freeze_dataset(rows: Iterable[Mapping], version: int) -> dict:
    cases = parse_cases(rows)
    return {
        "version": version,
        "digest": dataset_digest(cases),
        "cases": [asdict(case) for case in cases],
    }


def dataset_from_payload(payload: Mapping) -> FrozenDataset:
    cases = parse_cases(payload["cases"])
    require(dataset_digest(cases) == payload["digest"], "dataset content differs from its frozen digest")
    return FrozenDataset(payload["version"], payload["digest"], cases)


def load_dataset(path: Path) -> FrozenDataset:
    return dataset_from_payload(json.loads(Path(path).read_text(encoding="utf-8")))


def write_dataset(payload: Mapping, path: Path) -> None:
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def split_cases(dataset: FrozenDataset, split: str) -> tuple:
    require(split in SPLITS, f"split must be one of {SPLITS}")
    return tuple(case for case in dataset.cases if case.split == split)


def check_against_instances(dataset: FrozenDataset, specs: Iterable[InstanceSpec]) -> None:
    splits = {spec.name: spec.split for spec in specs}
    for case in dataset.cases:
        require(case.instance in splits, f"{case.case_id}: unknown instance '{case.instance}'")
        require(
            splits[case.instance] == case.split,
            f"{case.case_id}: split '{case.split}' differs from instance split '{splits[case.instance]}'",
        )
