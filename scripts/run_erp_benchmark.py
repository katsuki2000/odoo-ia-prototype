#!/usr/bin/env python3
"""Run the independent ERP bank with a runtime ORM oracle."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from config import settings
from evaluation.bench_common import latency_percentiles, mean, pct, run_on_model, seconds_text
from evaluation.erp_benchmark.bank import BankError, load_bank
from evaluation.erp_benchmark.plans import PLANS
from evaluation.preflight import probe_llm
from evaluation.erp_benchmark.runner import (
    BenchmarkConnectionError,
    XmlRpcReadSession,
    build_profile,
    oracle_record,
    result_from_record,
    score_answer,
)


def oracle_digest() -> str:
    payload = json.dumps(PLANS, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def append_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def run_oracle(questions, session, bank_sha256, output: Path, run_id: str, max_rows: int):
    digest = oracle_digest()
    records = []
    for question in questions:
        record = oracle_record(session, question, bank_sha256, digest, max_rows)
        record.update({
            "record_type": "oracle",
            "run_id": run_id,
            "required_modules": question["required_modules"],
            "operation_kind": question["operation_kind"],
            "relation_depth": question["relation_depth"],
        })
        records.append(record)
    append_jsonl(output, records)
    return records


def _backend_error(result: dict) -> str | None:
    if result.get("worker_error"):
        return result["worker_error"]
    errors = result.get("llm_errors") or []
    backend = [item for item in errors if any(marker in item.get("type", "").casefold() for marker in ("connection", "timeout", "network"))]
    return backend[0].get("type", "backend error") if backend else None


def _domain_shape(domain: list) -> list:
    """Logical operators and [field, operator] pairs of a domain: the values stay out of the captures."""
    return [token if isinstance(token, str) else list(token[:2]) for token in domain]


def _safe_tool_calls(calls: list[dict]) -> list[dict]:
    """Tool calls as recorded in the captures: names, models, keyword, domain shape and counts, no data values."""
    safe = []
    for call in calls:
        args = call.get("args") or {}
        item = {key: call[key] for key in ("name", "status", "error", "row_count", "covers_plan") if key in call}
        item.update({key: args[key] for key in ("model", "query") if key in args})
        if "domain" in args:
            item["domain"] = _domain_shape(args["domain"])
        safe.append(item)
    return safe


def run_model(oracle_records, questions_by_id, session, password, model, reasoning_effort, passes, output, run_id, timeout_seconds, context_length):
    from erp_data.agent.orm_agent_helpers import DOMAIN_QUERY_TOOLS
    from scripts.run_erp_model_eval import _run_isolated_question

    applicable = [record for record in oracle_records if record.get("oracle_status") == "ok"]
    emitted = []
    if not applicable:
        return emitted, 0

    def execute(server_info):
        for pass_number in range(1, passes + 1):
            for oracle_record_item in applicable:
                question = questions_by_id[oracle_record_item["question_id"]]
                started = time.monotonic()
                result = _run_isolated_question(
                    question["question"],
                    session.uid,
                    password,
                    model,
                    reasoning_effort,
                    timeout_seconds,
                    session.active_company_id,
                    session.allowed_company_ids or None,
                )
                elapsed = round(time.monotonic() - started, 1)
                answer = result.get("answer", "")
                read_data = any(
                    call.get("status") == "ok" and call["name"] in DOMAIN_QUERY_TOOLS | {"read"}
                    for call in result.get("tool_calls", [])
                )
                scored = score_answer(answer, result_from_record(oracle_record_item), read_data)
                record = {
                    "record_type": "model",
                    "run_id": run_id,
                    "model": model,
                    "profile": session.login,
                    "question_id": question["id"],
                    "question": question["question"],
                    "pass_number": pass_number,
                    "answer": answer,
                    "tool_calls": _safe_tool_calls(result.get("tool_calls", [])),
                    "tool_call_count": len(result.get("tool_calls", [])),
                    "tool_ok": sum(call.get("status") == "ok" for call in result.get("tool_calls", [])),
                    "tool_invalid": sum(call.get("status") == "invalid" for call in result.get("tool_calls", [])),
                    "tool_unknown": sum(call.get("status") == "unknown" for call in result.get("tool_calls", [])),
                    "timed_out": bool(result.get("timed_out")),
                    "error": _backend_error(result),
                    "seconds": elapsed,
                    "llm_calls": result.get("timing", {}).get("llm_call_count", 0),
                    "llm_error_count": len(result.get("llm_errors", [])),
                    "hops": result.get("timing", {}).get("hop_count", len(result.get("tool_calls", []))),
                    "query_plan": result.get("query_plan"),
                    "oracle_status": oracle_record_item["oracle_status"],
                    "instance_fingerprint": session.instance_fingerprint,
                    "server_version": session.server_version,
                    "bank_sha256": oracle_record_item["bank_sha256"],
                    "oracle_sha256": oracle_record_item["oracle_sha256"],
                    **scored,
                    **server_info,
                }
                append_jsonl(output, [record])
                emitted.append(record)
                print(
                    f"[{len(emitted)}/{len(applicable) * passes}] {question['id']} pass {pass_number}: "
                    f"facts {pct(record['fact_recall'])}, rows {pct(record['row_recall'])}, {elapsed}s",
                    flush=True,
                )
        return True

    exit_code = run_on_model(
        model,
        context_length,
        False,
        execute,
        probes={"llm": probe_llm},
    )
    return emitted, exit_code


def report(path: Path) -> None:
    records = [item for item in load_jsonl(path) if item.get("record_type") == "model"]
    if not records:
        print("No model result recorded.")
        return
    valid = [item for item in records if not item.get("error")]
    p50, p90 = latency_percentiles([item["seconds"] for item in valid])
    print("ERP benchmark evaluation")
    print(f"runs={len(records)} valid={len(valid)} errors={len(records) - len(valid)}")
    print(f"fact_recall={pct(mean([item['fact_recall'] for item in valid]))} complete={pct(mean([item['complete'] for item in valid]))}")
    print(f"row_recall={pct(mean([item['row_recall'] for item in valid if item['row_recall'] is not None]))} abstention={pct(mean([item['abstention'] for item in valid]))}")
    print(f"p50={seconds_text(p50)}s p90={seconds_text(p90)}s")
    print(f"question_ids={len({item['question_id'] for item in records})}")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank", type=Path, default=settings.ERP_BENCHMARK_BANK_PATH)
    parser.add_argument("--ids", nargs="+")
    parser.add_argument("--login")
    parser.add_argument("--password-env", default="ODOO_BENCH_PASSWORD")
    parser.add_argument("--model")
    parser.add_argument("--reasoning-effort")
    parser.add_argument("--passes", type=int, default=1)
    parser.add_argument("--context-length", type=int, default=32768)
    parser.add_argument("--max-rows", type=int, default=settings.ERP_BENCHMARK_MAX_ROWS)
    parser.add_argument("--output", type=Path, default=settings.ERP_BENCHMARK_CAPTURE_PATH)
    parser.add_argument("--oracle-only", action="store_true")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--report", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.report:
        report(args.output)
        return 0
    try:
        questions, bank_sha256 = load_bank(args.bank, args.ids)
    except BankError as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 2
    missing_plans = sorted({question["id"] for question in questions} - set(PLANS))
    if missing_plans:
        print(f"[ERROR] no oracle plan for: {missing_plans}", file=sys.stderr)
        return 2
    if args.validate:
        print(f"valid bank: {len(questions)} questions, bank_sha256={bank_sha256}")
        print(f"oracle plans: {len(PLANS)}, oracle_sha256={oracle_digest()}")
        return 0
    if not args.login:
        raise SystemExit("--login is required")
    if args.model and args.passes < 1:
        raise SystemExit("--passes must be at least 1")
    if args.max_rows < 1:
        raise SystemExit("--max-rows must be at least 1")
    if args.context_length < 1:
        raise SystemExit("--context-length must be at least 1")
    try:
        login, password = build_profile(args.login, args.password_env)
        session = XmlRpcReadSession(login, password)
    except (BankError, BenchmarkConnectionError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 2
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    oracle_records = run_oracle(questions, session, bank_sha256, args.output, run_id, args.max_rows)
    applicable = sum(record.get("oracle_status") == "ok" for record in oracle_records)
    print(f"oracle: {applicable}/{len(oracle_records)} applicable -> {args.output}")
    if not args.model or args.oracle_only:
        return 0
    _, exit_code = run_model(
        oracle_records,
        {question["id"]: question for question in questions},
        session,
        password,
        args.model,
        args.reasoning_effort,
        args.passes,
        args.output,
        run_id,
        settings.ERP_MODEL_EVAL_TIMEOUT_SECONDS,
        args.context_length,
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
