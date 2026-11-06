"""Execution, scoring and capture helpers for the independent ERP benchmark."""

from __future__ import annotations

import hashlib
import os
import time
import xmlrpc.client
from typing import Any

from config import settings
from evaluation.bench_common import contains_fact, normalize
from .bank import BankError
from .oracle import NotApplicable, OracleResult, evaluate_plan
from .plans import PLANS


class BenchmarkConnectionError(RuntimeError):
    """Raised when the authenticated XML-RPC session cannot be used."""


class XmlRpcReadSession:
    """A direct, read-only XML-RPC session authenticated as one benchmark profile."""

    def __init__(self, login: str, password: str, db: str | None = None, url: str | None = None):
        self.url = url or settings.ODOO_URL
        self.db = db or settings.ODOO_DB
        if not self.db:
            raise BenchmarkConnectionError("ODOO_DB must be set")
        self.login = login
        self._password = password
        self.common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self.models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")
        try:
            self.uid = self.common.authenticate(self.db, login, password, {})
        except Exception as error:
            raise BenchmarkConnectionError(f"authentication failed: {type(error).__name__}") from error
        if not self.uid:
            raise BenchmarkConnectionError(f"authentication failed for {login}")
        try:
            version = self.common.version()
        except Exception:
            version = {}
        self.server_version = version.get("server_version") if isinstance(version, dict) else None
        self.active_company_id, self.allowed_company_ids = self._load_company_context()
        fingerprint_input = f"{self.url}|{self.db}|{self.server_version}|{len(self.allowed_company_ids)}"
        self.instance_fingerprint = hashlib.sha256(fingerprint_input.encode("utf-8")).hexdigest()[:16]

    def _load_company_context(self) -> tuple[int | None, list[int]]:
        try:
            rows = self._execute_raw("res.users", "read", [[self.uid]], {"fields": ["company_id", "company_ids"]})
        except xmlrpc.client.Fault:
            return None, []
        if not rows:
            return None, []
        row = rows[0]
        company = row.get("company_id") or []
        active = company[0] if isinstance(company, list) and company and isinstance(company[0], int) else None
        allowed = row.get("company_ids") or []
        allowed = [item for item in allowed if isinstance(item, int)]
        if active is not None:
            # Odoo 17 takes the first allowed company as the current one.
            allowed = [active] + [item for item in allowed if item != active]
        return active, allowed

    def _execute_raw(self, model: str, method: str, args: list[Any], kwargs: dict[str, Any] | None = None) -> Any:
        return self.models.execute_kw(self.db, self.uid, self._password, model, method, args, kwargs or {})

    def execute(self, model: str, method: str, args: list[Any], kwargs: dict[str, Any] | None = None) -> Any:
        if not model or not isinstance(model, str) or any(character in model for character in "/\\"):
            raise BenchmarkConnectionError(f"invalid model name: {model!r}")
        allowed_models = settings.ODOO_ALLOWED_MODELS
        if allowed_models and model not in allowed_models:
            raise BenchmarkConnectionError(f"model is outside ODOO_ALLOWED_MODELS: {model}")
        options = dict(kwargs or {})
        context = dict(options.get("context") or {})
        if self.allowed_company_ids:
            context["allowed_company_ids"] = list(self.allowed_company_ids)
        if context:
            options["context"] = context
        return self._execute_raw(model, method, args, options)


def _empty_answer(answer: str) -> bool:
    folded = normalize(answer)
    markers = (
        "aucun",
        "aucune",
        "aucunenregistrement",
        "pasde",
        "neant",
        "0resultat",
        "norecord",
        "noresult",
        "none",
        "nothing",
    )
    return any(marker in folded for marker in markers)


def _abstention(answer: str) -> bool:
    folded = normalize(answer)
    markers = (
        "jenepeuxpas",
        "jen'aipasacces",
        "jenesaispas",
        "donneesindisponibles",
        "informationindisponible",
        "impossiblederepondre",
        "no_data_answer",
        "incomplete_query_answer",
    )
    return any(marker in folded for marker in markers)


def score_answer(answer: str, oracle: OracleResult) -> dict[str, Any]:
    if oracle.empty and oracle.kind in {"rows", "relation"}:
        correct = _empty_answer(answer)
        return {
            "fact_recall": 1.0 if correct else 0.0,
            "complete": correct,
            "row_recall": 1.0 if correct else 0.0,
            "abstention": _abstention(answer),
        }
    matches = [
        any(contains_fact(normalize(answer), fact) for fact in group)
        for group in oracle.expected_groups
    ]
    matched = sum(matches)
    fact_recall = matched / len(matches) if matches else 0.0
    row_matches = []
    cursor = 0
    for row in oracle.row_groups:
        row_length = len(row)
        row_matches.append(all(matches[cursor:cursor + row_length]))
        cursor += row_length
    return {
        "fact_recall": fact_recall,
        "complete": bool(matches) and matched == len(matches),
        "row_recall": sum(row_matches) / len(row_matches) if row_matches else None,
        "abstention": _abstention(answer),
    }


def evaluate_question(session: XmlRpcReadSession, question: dict[str, Any], max_rows: int) -> OracleResult:
    if question["id"] not in PLANS:
        raise BankError(f"no oracle plan for {question['id']}")
    return evaluate_plan(session, PLANS[question["id"]], max_rows=max_rows)


def oracle_record(
    session: XmlRpcReadSession,
    question: dict[str, Any],
    bank_digest: str,
    oracle_digest: str,
    max_rows: int,
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        result = evaluate_question(session, question, max_rows)
    except NotApplicable as error:
        return {
            "question_id": question["id"],
            "question": question["question"],
            "category": question["category"],
            "profile": session.login,
            "instance_fingerprint": session.instance_fingerprint,
            "server_version": session.server_version,
            "oracle_status": "not_evaluable",
            "oracle_reason": str(error),
            "oracle_seconds": round(time.monotonic() - started, 3),
            "bank_sha256": bank_digest,
            "oracle_sha256": oracle_digest,
        }
    return {
        "question_id": question["id"],
        "question": question["question"],
        "category": question["category"],
        "profile": session.login,
        "instance_fingerprint": session.instance_fingerprint,
        "server_version": session.server_version,
        "oracle_status": result.status,
        "oracle": result.as_dict(),
        "oracle_seconds": round(time.monotonic() - started, 3),
        "bank_sha256": bank_digest,
        "oracle_sha256": oracle_digest,
    }


def result_from_record(record: dict[str, Any]) -> OracleResult:
    data = record.get("oracle")
    if not isinstance(data, dict):
        raise ValueError(f"record has no oracle result: {record.get('question_id')}")
    return OracleResult(
        status=data["status"],
        kind=data["kind"],
        expected_groups=tuple(tuple(group) for group in data.get("expected_groups", [])),
        row_groups=tuple(tuple(tuple(group) for group in row) for row in data.get("row_groups", [])),
        value=data.get("value"),
        count=data.get("count"),
        rows=tuple(data.get("rows", [])),
        empty=bool(data.get("empty")),
        reason=data.get("reason"),
    )


def summarize_oracle(records: list[dict[str, Any]]) -> dict[str, Any]:
    applicable = [record for record in records if record.get("oracle_status") == "ok"]
    skipped = [record for record in records if record.get("oracle_status") != "ok"]
    return {
        "selected": len(records),
        "applicable": len(applicable),
        "not_evaluable": len(skipped),
        "coverage": len(applicable) / len(records) if records else 0.0,
        "reasons": {
            reason: sum(item.get("oracle_reason") == reason for item in skipped)
            for reason in sorted({item.get("oracle_reason") for item in skipped if item.get("oracle_reason")})
        },
    }


def build_profile(login: str, password_env: str = "ODOO_BENCH_PASSWORD") -> tuple[str, str]:
    password = os.getenv(password_env, "")
    if not password:
        raise BenchmarkConnectionError(f"{password_env} is not set")
    return login, password
