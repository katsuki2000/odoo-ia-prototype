"""Load and validate the blind ERP question bank."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = frozenset({
    "id",
    "language",
    "category",
    "question",
    "required_modules",
    "operation_kind",
    "relation_depth",
    "profile_required",
    "ambiguity_risk",
})
ALLOWED_CATEGORIES = frozenset({
    "Comptage / agrégation",
    "Liste / filtre",
    "Relation entre modèles",
    "Valeur individuelle",
    "Cas sans résultat",
    "Profil de droits",
})
ALLOWED_AMBIGUITY = frozenset({"faible", "moyen", "élevé", "low", "medium", "high"})
FORBIDDEN_FIELDS = frozenset({
    "answer",
    "expected",
    "expected_answer",
    "expected_answers",
    "expected_facts",
    "ground_truth",
    "oracle",
    "record_ids",
    "sql",
})


class BankError(ValueError):
    """Raised when a question bank violates its authoring contract."""


def _error(line: int, message: str) -> BankError:
    return BankError(f"{line}: {message}")


def validate_question(question: dict[str, Any], line: int) -> None:
    if not isinstance(question, dict):
        raise _error(line, "each JSONL record must be an object")
    missing = REQUIRED_FIELDS - question.keys()
    if missing:
        raise _error(line, f"missing fields: {sorted(missing)}")
    forbidden = FORBIDDEN_FIELDS & question.keys()
    if forbidden:
        raise _error(line, f"oracle or answer fields are forbidden: {sorted(forbidden)}")
    unknown = set(question) - REQUIRED_FIELDS
    if unknown:
        raise _error(line, f"unknown fields: {sorted(unknown)}")
    if not isinstance(question["id"], str) or not question["id"].strip():
        raise _error(line, "id must be a non-empty string")
    if question["language"] != "fr":
        raise _error(line, "language must be 'fr'")
    if question["category"] not in ALLOWED_CATEGORIES:
        raise _error(line, f"unsupported category: {question['category']!r}")
    if not isinstance(question["question"], str) or not question["question"].strip():
        raise _error(line, "question must be a non-empty string")
    modules = question["required_modules"]
    if not isinstance(modules, list) or not modules or any(not isinstance(item, str) or not item for item in modules):
        raise _error(line, "required_modules must be a non-empty list of strings")
    if not isinstance(question["operation_kind"], str) or not question["operation_kind"]:
        raise _error(line, "operation_kind must be a non-empty string")
    if not isinstance(question["relation_depth"], int) or question["relation_depth"] not in {0, 1, 2}:
        raise _error(line, "relation_depth must be 0, 1 or 2")
    if not isinstance(question["profile_required"], bool):
        raise _error(line, "profile_required must be boolean")
    if question["ambiguity_risk"] not in ALLOWED_AMBIGUITY:
        raise _error(line, f"unsupported ambiguity_risk: {question['ambiguity_risk']!r}")
    if question["category"] == "Profil de droits" and not question["profile_required"]:
        raise _error(line, "rights questions must require a profile")


def load_bank(path: str | Path, ids: list[str] | None = None) -> tuple[list[dict[str, Any]], str]:
    """Return validated questions and the SHA-256 of the exact JSONL file."""
    source = Path(path)
    if not source.is_file():
        raise BankError(f"question bank does not exist: {source}")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    questions: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_questions: set[str] = set()
    for line_number, raw_line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip():
            continue
        try:
            question = json.loads(raw_line)
        except json.JSONDecodeError as error:
            raise _error(line_number, f"invalid JSON: {error.msg}") from error
        validate_question(question, line_number)
        if question["id"] in seen_ids:
            raise _error(line_number, f"duplicate id: {question['id']}")
        if question["question"] in seen_questions:
            raise _error(line_number, f"duplicate question: {question['question']}")
        seen_ids.add(question["id"])
        seen_questions.add(question["question"])
        questions.append(question)
    selected = [item for item in questions if not ids or item["id"] in set(ids)]
    missing_ids = sorted(set(ids or ()) - {item["id"] for item in questions})
    if missing_ids:
        raise BankError(f"unknown question ids: {missing_ids}")
    if not selected:
        raise BankError("question bank selection is empty")
    return selected, digest
