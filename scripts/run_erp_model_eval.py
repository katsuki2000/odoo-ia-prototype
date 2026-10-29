#!/usr/bin/env python3
"""Compare supported Ollama models on authenticated, read-only Odoo questions."""

import argparse
import json
import multiprocessing
import queue
import sys
import time
import xmlrpc.client
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from config import settings
from core.evaluation import run_store
from core.evaluation.bench_common import (
    contains_fact,
    execute_runs,
    latency_percentiles,
    mean,
    normalize,
    pct,
    rescore_runs,
    run_on_model,
    seconds_text,
)
from core.evaluation.erp_model_worker import run_question as run_question_worker
from core.evaluation.preflight import BackendUnavailable, probe_llm
from erp_data.odoo_connector import OdooConnector, OdooConnectorError

QUESTIONS_PATH = project_root / "tests" / "benchmark_questions.json"
RESULTS_PATH = project_root / "captures" / "erp_model_eval.jsonl"
QUESTION_TIMEOUT_SECONDS = settings.ERP_MODEL_EVAL_TIMEOUT_SECONDS


def load_questions(ids):
    with QUESTIONS_PATH.open(encoding="utf-8") as file:
        questions = json.load(file)["questions"]
    questions = [item for item in questions if item["category"] == "erp_chiffre"]
    return [item for item in questions if not ids or item["id"] in ids]


def authenticate_odoo(login, password):
    connector = OdooConnector(db=settings.ODOO_DB, password=password)
    uid = connector.common.authenticate(connector.db, login, password, {})
    if not uid:
        raise BackendUnavailable(f"Odoo authentication failed for {login}.")
    return uid


def _run_isolated_question(question, uid, password, model, timeout_seconds):
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    process = context.Process(
        target=run_question_worker,
        args=(question, uid, password, settings.ODOO_DB, model, result_queue),
    )
    try:
        process.start()
    except OSError as error:
        result_queue.close()
        result_queue.join_thread()
        return {"worker_error": type(error).__name__}
    deadline = time.monotonic() + timeout_seconds
    tool_calls = []
    llm_errors = []
    llm_call_count = 0
    result = None

    def collect_messages():
        nonlocal result, llm_call_count
        while True:
            try:
                message = result_queue.get_nowait()
            except queue.Empty:
                return
            if message["event"] == "tool_call":
                tool_calls.append(message["call"])
            elif message["event"] == "llm_error":
                llm_errors.append(message["error"])
            elif message["event"] == "llm_call":
                llm_call_count += 1
            else:
                result = message["result"]

    try:
        while process.is_alive() and time.monotonic() < deadline:
            process.join(min(0.1, max(0, deadline - time.monotonic())))
            collect_messages()
        timed_out = process.is_alive()
        if timed_out:
            process.terminate()
            process.join()
        collect_messages()
        if timed_out:
            return {
                "timed_out": True,
                "tool_calls": tool_calls,
                "llm_errors": llm_errors,
                "timing": {"llm_call_count": llm_call_count, "hop_count": len(tool_calls)},
            }
        if result is None:
            return {
                "worker_error": f"Worker exited with status {process.exitcode} without a result.",
                "tool_calls": tool_calls,
                "llm_errors": llm_errors,
            }
        return result
    except BaseException:
        if process.is_alive():
            process.terminate()
            process.join()
        raise
    finally:
        result_queue.close()
        result_queue.join_thread()


def score(item, answer):
    folded_answer = normalize(answer)
    facts = item["expected_answer_contains"]
    found = sum(contains_fact(folded_answer, fact) for fact in facts)
    return {
        "fact_recall": found / len(facts) if facts else None,
        "complete": found == len(facts) if facts else None,
    }


def _is_backend_error(error):
    return any(
        marker in error.get("type", "").casefold()
        for marker in ("connection", "timeout", "network")
    ) or error.get("module", "").startswith(("httpx", "httpcore", "requests", "urllib3"))


def run_once(item, uid, password, model):
    started_at = time.monotonic()
    result = _run_isolated_question(
        item["question"], uid, password, model, QUESTION_TIMEOUT_SECONDS,
    )
    seconds = round(time.monotonic() - started_at, 1)
    answer = result.get("answer", "")
    calls = result.get("tool_calls", [])
    llm_errors = result.get("llm_errors", [])
    worker_error = result.get("worker_error")
    timed_out = result.get("timed_out", False)
    backend_errors = [error for error in llm_errors if _is_backend_error(error)]
    error = worker_error or (
        f"{backend_errors[0]['type']} ({backend_errors[0]['module']})" if backend_errors else None
    )
    return {
        "answer": answer,
        "answer_chars": len(answer),
        "tool_calls": calls,
        "tool_call_count": len(calls),
        "tool_ok": sum(call["status"] == "ok" for call in calls),
        "tool_invalid": sum(call["status"] == "invalid" for call in calls),
        "tool_unknown": sum(call["status"] == "unknown" for call in calls),
        "no_tool": None if timed_out else not calls,
        "llm_calls": result.get("timing", {}).get("llm_call_count", 0),
        "llm_error_count": len(llm_errors),
        "hops": result.get("timing", {}).get("hop_count", len(calls)),
        "llm_errors": llm_errors,
        "seconds": seconds,
        "timed_out": timed_out,
        "error": error,
        **score(item, answer),
    }


def load_scored_runs():
    questions = load_questions(None)
    return rescore_runs(
        run_store.load_runs(RESULTS_PATH),
        questions,
        lambda item, record: score(item, record["answer"]),
    )


def describe(record):
    if record["timed_out"]:
        return "timed out"
    if record["error"]:
        return "error"
    return f'facts {pct(record["fact_recall"])}, tools {record["tool_call_count"]}'


def execute(todo, runs, model, server_info, uid, password):
    def build_record(item, pass_number):
        return {
            "model": model,
            "question_id": item["id"],
            "pass_number": pass_number,
            "question": item["question"],
            **server_info,
            **run_once(item, uid, password, model),
        }

    return execute_runs(todo, runs, RESULTS_PATH, build_record, describe)


def model_stats(records):
    errors = [record for record in records if record["error"]]
    valid = [record for record in records if not record["error"]]
    p50, p90 = latency_percentiles([record["seconds"] for record in valid])
    return {
        "runs": len(records),
        "errors": len(errors),
        "timed_out": mean([record["timed_out"] for record in valid]),
        "facts": mean([record["fact_recall"] for record in valid]),
        "complete": mean([record["complete"] for record in valid]),
        "no_tool": mean([record["no_tool"] for record in valid if record["no_tool"] is not None]),
        "tool_calls": mean([record["tool_call_count"] for record in valid]),
        "tool_ok": sum(record["tool_ok"] for record in valid),
        "tool_invalid": sum(record["tool_invalid"] for record in valid),
        "tool_unknown": sum(record["tool_unknown"] for record in valid),
        "llm_calls": mean([record["llm_calls"] for record in valid]),
        "llm_errors": sum(record["llm_error_count"] for record in valid),
        "hops": mean([record["hops"] for record in valid]),
        "p50": p50,
        "p90": p90,
        "vram": min(
            (record["vram_fraction"] for record in records if record.get("vram_fraction") is not None),
            default=None,
        ),
    }


def print_report(runs):
    records = list(runs.values())
    models = sorted({record["model"] for record in records})
    if not models:
        print("No result recorded.")
        return
    print("\nERP agent evaluation (backend errors are excluded from rates)")
    print(f'{"model":<22}{"runs":>5}{"err":>5}{"tout":>7}{"facts":>7}{"full":>7}{"noTool":>8}'
          f'{"tools":>7}{"ok":>6}{"invalid":>9}{"unkn":>6}{"LLM":>6}{"LLMerr":>8}{"hops":>6}'
          f'{"p50s":>7}{"p90s":>7}{"vram":>6}')
    for model in models:
        stats = model_stats([record for record in records if record["model"] == model])
        vram = "n/a" if stats["vram"] is None else f'{stats["vram"]:.2f}'
        print(
            f'{model:<22}{stats["runs"]:>5}{stats["errors"]:>5}{pct(stats["timed_out"]):>7}'
            f'{pct(stats["facts"]):>7}{pct(stats["complete"]):>7}{pct(stats["no_tool"]):>8}'
            f'{seconds_text(stats["tool_calls"]):>7}{stats["tool_ok"]:>6}{stats["tool_invalid"]:>9}'
            f'{stats["tool_unknown"]:>6}{seconds_text(stats["llm_calls"]):>6}{stats["llm_errors"]:>8}'
            f'{seconds_text(stats["hops"]):>6}'
            f'{seconds_text(stats["p50"]):>7}{seconds_text(stats["p90"]):>7}{vram:>6}'
        )
    print("\nfacts = share of expected phrases/values found; full = all expected items found;")
    print("noTool = answer generated without an ORM call; invalid = tool call failed/refused;")
    print("timeouts count as unsuccessful answers, but are reported separately from backend errors.")
    question_ids = dict.fromkeys(record["question_id"] for record in records)
    print(f'\nper question (timeouts count as zero facts)\n{"question":<12}'
          + "".join(f'{model[:20]:>22}' for model in models))
    for question_id in question_ids:
        cells = []
        for model in models:
            rows = [
                row for row in records
                if row["model"] == model and row["question_id"] == question_id and not row["error"]
            ]
            cells.append(pct(mean([row["fact_recall"] for row in rows])) if rows else "-")
        print(f'{question_id:<12}' + "".join(f"{cell:>22}" for cell in cells))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare Ollama models on read-only Odoo questions.")
    parser.add_argument("--model", help="Ollama model name, as listed by `ollama list`")
    parser.add_argument("--ids", nargs="+", help="restrict to ERP question ids")
    parser.add_argument("--passes", type=int, default=3, help="repetitions per question (default: 3)")
    parser.add_argument("--context-length", type=int, default=32768, help="required Ollama context length")
    parser.add_argument("--login", help="Odoo user login for the benchmark (required for a run)")
    parser.add_argument("--retry-errors", action="store_true", help="rerun recorded backend/worker errors")
    parser.add_argument("--fresh", action="store_true", help="discard recorded runs for this model first")
    parser.add_argument("--keep-loaded", action="store_true", help="do not unload the model at the end")
    parser.add_argument("--report", action="store_true", help="report saved results and exit")
    args = parser.parse_args(argv)

    if args.report:
        print_report(load_scored_runs())
        return 0
    if not args.model:
        parser.error("--model is required unless --report is given")
    if not args.login:
        parser.error("--login is required for an Odoo evaluation")
    if args.passes < 1:
        parser.error("--passes must be at least 1")
    if args.context_length < 1:
        parser.error("--context-length must be at least 1")
    password = settings.ODOO_MANAGER_PASSWORD
    if not password:
        parser.error("ODOO_MANAGER_PASSWORD must be set in the backend .env")

    questions = load_questions(args.ids)
    if not questions:
        parser.error("No ERP question matches the filters.")
    if args.fresh:
        run_store.discard_model(RESULTS_PATH, args.model)
    runs = load_scored_runs()
    todo = list(run_store.pending_runs(
        args.model, questions, args.passes, runs,
        lambda previous: args.retry_errors and bool(previous["error"]),
    ))
    if not todo:
        print_report(runs)
        return 0

    try:
        uid = authenticate_odoo(args.login, password)
    except (BackendUnavailable, OSError, xmlrpc.client.Error, OdooConnectorError) as error:
        print(f"[ERROR] Odoo authentication/preflight failed: {type(error).__name__}")
        return 2
    print(f"Authenticated to Odoo as {args.login} (uid {uid}).")
    exit_code = run_on_model(
        args.model,
        args.context_length,
        args.keep_loaded,
        lambda server_info: execute(todo, runs, args.model, server_info, uid, password),
        probes={"llm": probe_llm},
    )
    print_report(runs)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
