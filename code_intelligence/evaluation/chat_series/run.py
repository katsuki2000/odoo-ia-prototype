"""CLI: run one chat series (section 1293) end to end against the live /api/v1/ask endpoint."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Sequence

import requests

from code_intelligence.evaluation.e1.run import persist_report


logger = logging.getLogger(__name__)

SERIES_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[3] / "captures"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
BASE_URL_ENV = "CHAT_SERIES_BASE_URL"
TOKEN_ENV = "CHAT_SERIES_API_TOKEN"
FROZEN_STATUS = "frozen"
CLIENT_ERROR_STATUSES = {400, 401, 403, 422}
TOKEN_LIFETIME_S = 6 * 3600
RESUME_KEYS = ("user_uid", "company_id", "source_mode", "language_mode", "groups")


@dataclass(frozen=True)
class RunSettings:
    base_url: str
    user_uid: int = 2
    company_id: int = 1
    source_mode: Optional[str] = None
    language_mode: str = "none"
    timeout_s: float = 600.0
    max_consecutive_failures: int = 3
    groups: tuple[str, ...] = ()

    def __post_init__(self):
        numeric = [group for group in self.groups if "." not in group]
        if numeric:
            raise ValueError(f"groups must be xml_ids (module.name), got: {', '.join(numeric)}")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def series_path(number: int) -> Path:
    return SERIES_DIR / f"series_{number}.json"


def load_series(path: Path) -> tuple[dict, str]:
    raw = Path(path).read_bytes()
    return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()


def ensure_runnable(series: dict, allow_draft: bool) -> None:
    """The protocol fixes questions and expected answers before the first run."""
    if series.get("status") != FROZEN_STATUS and not allow_draft:
        raise ValueError(
            f"series {series.get('series')} has status {series.get('status')!r}, not {FROZEN_STATUS!r}: "
            "validate and freeze it before the first run (or pass --allow-draft for a dry run)"
        )


def build_request(case: dict, settings: RunSettings, session_id: str) -> dict:
    payload = {
        "question": case["question"],
        "session_id": session_id,
        "user_uid": settings.user_uid,
        "company_id": settings.company_id,
    }
    if settings.source_mode:
        payload["source_mode"] = settings.source_mode
    if settings.language_mode == "case" and case.get("language"):
        payload["language"] = case["language"].replace("_", "-")
    return payload


def classify_outcome(status_code: Optional[int], body: Optional[dict]) -> str:
    if status_code is None or status_code == 503:
        return "transport_error"
    if status_code == 200:
        return "ok" if body is not None else "server_error"
    if status_code in CLIENT_ERROR_STATUSES:
        return "client_error"
    return "server_error"


def ask_case(post: Callable, case: dict, settings: RunSettings, headers: dict) -> dict:
    payload = build_request(case, settings, f"chat_series_{case['series']}_{case['case_id']}_{uuid.uuid4().hex[:8]}")
    started_at = utc_now()
    began = time.perf_counter()
    status_code, body, error = None, None, None
    try:
        response = post(
            f"{settings.base_url.rstrip('/')}/api/v1/ask", json=payload, headers=headers, timeout=settings.timeout_s,
        )
        status_code = response.status_code
        if status_code == 200:
            body = response.json()
        else:
            error = response.text[:500]
    except (requests.RequestException, ValueError) as exc:
        error = f"{type(exc).__name__}: {exc}"
    return {
        "case_id": case["case_id"],
        "anchor": bool(case.get("anchor")),
        "request": payload,
        "started_at": started_at,
        "latency_s": round(time.perf_counter() - began, 2),
        "transport_status": classify_outcome(status_code, body),
        "http_status": status_code,
        "error": error,
        "response": body,
    }


def new_report(series: dict, series_digest: str, settings: RunSettings) -> dict:
    now = utc_now()
    return {
        "series": series["series"],
        "series_status": series.get("status"),
        "series_digest": series_digest,
        "settings": asdict(settings),
        "started_at": now,
        "updated_at": now,
        "status": "running",
        "aborted_reason": None,
        "results": {},
        "invalidated_attempts": [],
    }


def check_resumable(previous: dict, series_digest: str, settings: RunSettings) -> None:
    if previous.get("series_digest") != series_digest:
        raise ValueError("the series file changed since the report was started: use a new output file")
    current = json.loads(json.dumps(asdict(settings)))
    recorded = previous.get("settings", {})
    changed = [key for key in RESUME_KEYS if (recorded.get(key) or None) != (current[key] or None)]
    if changed:
        raise ValueError(f"settings differ from the report being resumed: {', '.join(changed)}")


def run_series(
    series: dict,
    series_digest: str,
    *,
    settings: RunSettings,
    post: Callable,
    headers: dict,
    output_path: Optional[Path] = None,
    previous: Optional[dict] = None,
    only: Optional[Sequence[str]] = None,
) -> dict:
    """Ask each case once, saving after every question; only transport-clean answers are results."""
    case_ids = {case["case_id"] for case in series["cases"]}
    unknown = set(only or ()) - case_ids
    if unknown:
        raise ValueError(f"unknown case ids: {', '.join(sorted(unknown))}")
    if previous is None:
        report = new_report(series, series_digest, settings)
    else:
        check_resumable(previous, series_digest, settings)
        report = previous
        report["status"], report["aborted_reason"] = "running", None
    selected = [case for case in series["cases"] if not only or case["case_id"] in only]
    consecutive_failures = 0
    for position, case in enumerate(selected, start=1):
        if case["case_id"] in report["results"]:
            continue
        record = ask_case(post, case, settings, headers)
        outcome = record["transport_status"]
        if outcome == "ok":
            report["results"][case["case_id"]] = record
            consecutive_failures = 0
        else:
            report["invalidated_attempts"].append(record)
            consecutive_failures += 1
        report["updated_at"] = utc_now()
        persist_report(report, output_path)
        logger.info(
            "[%d/%d] %s %s %.1fs route=%s", position, len(selected), case["case_id"], outcome,
            record["latency_s"], (record["response"] or {}).get("route"),
        )
        if outcome == "client_error":
            report["aborted_reason"] = f"client_error HTTP {record['http_status']}: {record['error']}"
            break
        if consecutive_failures >= settings.max_consecutive_failures:
            report["aborted_reason"] = f"{consecutive_failures} consecutive failed questions"
            break
    report["status"] = "complete" if case_ids <= set(report["results"]) else "incomplete"
    report["updated_at"] = utc_now()
    persist_report(report, output_path)
    return report


def load_previous_report(path: Optional[Path]) -> Optional[dict]:
    if path is None or not Path(path).is_file():
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def mint_token(user_uid: int, company_id: int, groups: Sequence[str] = ()) -> str:
    """Local development token signed with the API secret; importing config.settings loads .env."""
    importlib.import_module("config.settings")
    import jwt

    from api.auth import get_jwt_secret

    claims = {"sub": str(user_uid), "uid": user_uid, "company_id": company_id, "exp": int(time.time()) + TOKEN_LIFETIME_S}
    if groups:
        claims["groups"] = list(groups)
    return jwt.encode(claims, get_jwt_secret(), algorithm="HS256")


def build_headers(settings: RunSettings) -> dict:
    token = os.getenv(TOKEN_ENV)
    if token and settings.groups:
        raise ValueError(f"--groups is ignored when {TOKEN_ENV} is set: the real token carries its own groups")
    token = token or mint_token(settings.user_uid, settings.company_id, settings.groups)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run one end-to-end chat series against a running API.")
    parser.add_argument("--series", type=int, required=True, help="Series number (data/series_<n>.json).")
    parser.add_argument("--output", type=Path, help="JSON report, rewritten after each question and resumable.")
    parser.add_argument("--base-url", default=os.getenv(BASE_URL_ENV, DEFAULT_BASE_URL))
    parser.add_argument("--user-uid", type=int, default=2)
    parser.add_argument("--company-id", type=int, default=1)
    parser.add_argument("--source-mode", choices=["documentation", "systeme"], default=None,
                        help="Default: automatic routing, as in the chat interface.")
    parser.add_argument("--language", choices=["none", "case"], default="none", dest="language_mode",
                        help="'none' sends no language, as the chat interface does today; 'case' sends the case language.")
    parser.add_argument("--groups", nargs="+", default=[], metavar="XMLID",
                        help="Group xml_ids put in the local token (e.g. base.group_user); ignored by a real token.")
    parser.add_argument("--timeout", type=float, default=600.0, help="Seconds to wait for one answer.")
    parser.add_argument("--max-consecutive-failures", type=int, default=3)
    parser.add_argument("--only", nargs="+", help="Case ids to ask (default: the whole series).")
    parser.add_argument("--allow-draft", action="store_true", help="Run a series that is not frozen (dry run only).")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    output_path = args.output or DEFAULT_OUTPUT_DIR / f"chat_series_{args.series}.json"
    try:
        settings = RunSettings(
            base_url=args.base_url, user_uid=args.user_uid, company_id=args.company_id, source_mode=args.source_mode,
            language_mode=args.language_mode, timeout_s=args.timeout,
            max_consecutive_failures=args.max_consecutive_failures, groups=tuple(args.groups),
        )
        series, digest = load_series(series_path(args.series))
        ensure_runnable(series, args.allow_draft)
        report = run_series(
            series, digest, settings=settings, post=requests.post, headers=build_headers(settings),
            output_path=output_path, previous=load_previous_report(output_path), only=args.only,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    answered = len(report["results"])
    total = len(series["cases"])
    print(
        f"status={report['status']} answered={answered}/{total} "
        f"invalidated_attempts={len(report['invalidated_attempts'])} report={output_path}"
    )
    if report["aborted_reason"]:
        print(f"aborted: {report['aborted_reason']}")
        return 1
    return 0 if report["status"] == "complete" else 3


if __name__ == "__main__":
    sys.exit(main())
