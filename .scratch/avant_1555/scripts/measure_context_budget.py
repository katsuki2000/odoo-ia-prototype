#!/usr/bin/env python3
"""
scripts/measure_context_budget.py

Measure the REAL context budget consumed by the agent on Bloc N1 questions
(section 1067 of todo/contexte.txt). No production code is modified: the script
wraps ChatOpenAI._generate/_agenerate at class level and records, for every LLM
call, the token usage reported by the server, the finish reason, the message
sizes per role and the size of any "thinking" output.

Interpretation criteria (fixed BEFORE measuring, see section 1067). The window
is considered limiting if, on at least one call:
  - prompt + completion >= 90 % of the window, or
  - finish_reason == "length", or
  - llm_client logged a "contexte reduit" event (silent context reduction).
Otherwise the window is not the bottleneck on the measured questions.
Known caveat: a server may truncate an over-long prompt without any error, so a
prompt_tokens value glued to the window is suspect even without other signals.

Usage (requires the LLM server to be reachable, same .env as the pipeline):
    python scripts/measure_context_budget.py
    python scripts/measure_context_budget.py --ids PUR-Q5 STK-Q5 SAL-Q5
    python scripts/measure_context_budget.py --all --out report.json
    LLM_CONTEXT_WINDOW=32768 python scripts/measure_context_budget.py
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

QUESTION_BANK = project_root / "tests" / "native_n1_question_bank.json"
DEFAULT_IDS = ["PUR-Q5", "STK-Q5"]
LIMITING_RATIO = 0.90
SUSPECT_TRUNCATION_RATIO = 0.98
_THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL)


def _content_chars(content: Any) -> int:
    if content is None:
        return 0
    if isinstance(content, str):
        return len(content)
    return len(json.dumps(content, ensure_ascii=False, default=str))


def _message_sizes(messages: List[Any]) -> Dict[str, int]:
    sizes: Dict[str, int] = {}
    for m in messages:
        role = getattr(m, "type", type(m).__name__)
        chars = _content_chars(getattr(m, "content", ""))
        tool_calls = getattr(m, "tool_calls", None) or []
        if tool_calls:
            chars += len(json.dumps(tool_calls, ensure_ascii=False, default=str))
        sizes[role] = sizes.get(role, 0) + chars
    return sizes


class Recorder:
    """Collects one entry per LLM call; entries are tagged with the current question id."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.current_id: Optional[str] = None
        self.context_reductions: Dict[str, int] = {}

    def record(self, messages, result, elapsed: float, error: Optional[str]) -> None:
        entry: Dict[str, Any] = {
            "question_id": self.current_id,
            "n_messages": len(messages),
            "chars_by_role": _message_sizes(messages),
            "elapsed_s": round(elapsed, 2),
            "error": error,
        }
        if result is not None:
            llm_output = getattr(result, "llm_output", None) or {}
            usage = dict(llm_output.get("token_usage") or {})
            gen = result.generations[0] if result.generations else None
            msg = getattr(gen, "message", None)
            if not usage and msg is not None:
                meta = getattr(msg, "usage_metadata", None) or {}
                usage = {
                    "prompt_tokens": meta.get("input_tokens"),
                    "completion_tokens": meta.get("output_tokens"),
                    "total_tokens": meta.get("total_tokens"),
                }
            info = getattr(gen, "generation_info", None) or {}
            text = _content_chars(getattr(msg, "content", "")) if msg is not None else 0
            think_chars = 0
            if msg is not None and isinstance(getattr(msg, "content", None), str):
                think_chars = sum(len(t) for t in _THINK_RE.findall(msg.content))
            extra = getattr(msg, "additional_kwargs", None) or {}
            for key in ("reasoning_content", "reasoning"):
                if isinstance(extra.get(key), str):
                    think_chars += len(extra[key])
            details = usage.get("completion_tokens_details") or {}
            entry.update(
                {
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "total_tokens": usage.get("total_tokens"),
                    "reasoning_tokens": details.get("reasoning_tokens"),
                    "finish_reason": info.get("finish_reason"),
                    "answer_chars": text,
                    "think_chars": think_chars,
                    "has_tool_calls": bool(getattr(msg, "tool_calls", None)),
                }
            )
        self.calls.append(entry)


class _ReductionHandler(logging.Handler):
    """Counts the 'contexte reduit' warnings emitted by core.llm.llm_client."""

    def __init__(self, recorder: Recorder) -> None:
        super().__init__(level=logging.WARNING)
        self.recorder = recorder

    def emit(self, record: logging.LogRecord) -> None:
        text = record.getMessage().lower()
        if "contexte r" in text and "duit" in text:
            key = self.recorder.current_id or "?"
            self.recorder.context_reductions[key] = self.recorder.context_reductions.get(key, 0) + 1


def install_probe(recorder: Recorder) -> None:
    from langchain_openai import ChatOpenAI

    orig_sync = ChatOpenAI._generate
    orig_async = ChatOpenAI._agenerate

    def wrapped_sync(self, messages, *args, **kwargs):
        t0 = time.time()
        try:
            res = orig_sync(self, messages, *args, **kwargs)
        except Exception as exc:  # recorded then re-raised: behaviour unchanged
            recorder.record(messages, None, time.time() - t0, f"{type(exc).__name__}: {exc}"[:300])
            raise
        recorder.record(messages, res, time.time() - t0, None)
        return res

    async def wrapped_async(self, messages, *args, **kwargs):
        t0 = time.time()
        try:
            res = await orig_async(self, messages, *args, **kwargs)
        except Exception as exc:
            recorder.record(messages, None, time.time() - t0, f"{type(exc).__name__}: {exc}"[:300])
            raise
        recorder.record(messages, res, time.time() - t0, None)
        return res

    ChatOpenAI._generate = wrapped_sync
    ChatOpenAI._agenerate = wrapped_async
    logging.getLogger("core.llm.llm_client").addHandler(_ReductionHandler(recorder))


def summarize(question_id: str, calls: List[Dict[str, Any]], reductions: int, window: int) -> Dict[str, Any]:
    ok = [c for c in calls if c.get("prompt_tokens") is not None]
    max_prompt = max((c["prompt_tokens"] for c in ok), default=None)
    max_total = max(
        ((c["prompt_tokens"] or 0) + (c.get("completion_tokens") or 0) for c in ok), default=None
    )
    ratio = (max_total / window) if (max_total is not None and window) else None
    length_cuts = sum(1 for c in calls if c.get("finish_reason") == "length")
    suspect = [
        i for i, c in enumerate(ok)
        if c["prompt_tokens"] >= window * SUSPECT_TRUNCATION_RATIO
    ]
    chars = sum(sum(c["chars_by_role"].values()) for c in ok)
    prompt_total = sum(c["prompt_tokens"] for c in ok)
    limiting = bool(
        (ratio is not None and ratio >= LIMITING_RATIO) or length_cuts > 0 or reductions > 0
    )
    return {
        "question_id": question_id,
        "llm_calls": len(calls),
        "calls_with_usage": len(ok),
        "calls_with_error": sum(1 for c in calls if c.get("error")),
        "max_prompt_tokens": max_prompt,
        "max_prompt_plus_completion_tokens": max_total,
        "max_pct_of_window": round(ratio * 100, 1) if ratio is not None else None,
        "sum_prompt_tokens": prompt_total,
        "sum_completion_tokens": sum((c.get("completion_tokens") or 0) for c in ok),
        "sum_reasoning_tokens": sum((c.get("reasoning_tokens") or 0) for c in ok),
        "think_chars_total": sum(c.get("think_chars", 0) for c in calls),
        "finish_reason_length": length_cuts,
        "context_reductions_logged": reductions,
        "suspect_silent_truncation_calls": suspect,
        "approx_chars_per_token": round(chars / prompt_total, 2) if prompt_total else None,
        "window_is_limiting": limiting,
    }


def load_questions(ids: Optional[List[str]], take_all: bool) -> List[Dict[str, Any]]:
    data = json.loads(QUESTION_BANK.read_text(encoding="utf-8"))
    questions = data["questions"]
    if take_all:
        return questions
    wanted = set(ids or DEFAULT_IDS)
    selected = [q for q in questions if q["id"] in wanted]
    missing = wanted - {q["id"] for q in selected}
    if missing:
        raise SystemExit(f"Unknown question id(s): {sorted(missing)}")
    return selected


def main() -> int:
    env_window = os.getenv("LLM_CONTEXT_WINDOW")
    parser = argparse.ArgumentParser(description="Measure the real LLM context budget per question.")
    parser.add_argument("--ids", nargs="*", help=f"Question ids (default: {' '.join(DEFAULT_IDS)})")
    parser.add_argument("--all", action="store_true", help="Run all 25 Bloc N1 questions (long).")
    parser.add_argument("--window", type=int, default=int(env_window) if env_window else 32768,
                        help="Context window in tokens (env LLM_CONTEXT_WINDOW, explicit fallback 32768).")
    parser.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "context_budget_report.json"))
    args = parser.parse_args()

    source = "env LLM_CONTEXT_WINDOW" if env_window else "explicit fallback 32768 (set LLM_CONTEXT_WINDOW to override)"
    print(f"[config] window={args.window} tokens ({source})")

    questions = load_questions(args.ids, args.all)
    from core.graph.graph import code_intelligence_agent  # imported late: loads .env and the graph

    recorder = Recorder()
    install_probe(recorder)

    summaries: List[Dict[str, Any]] = []
    for q in questions:
        recorder.current_id = q["id"]
        start = len(recorder.calls)
        print(f"\n[run] {q['id']} -- {q['question'][:90]}...")
        error = None
        try:
            code_intelligence_agent({"question": q["question"], "chat_history": []})
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:300]
            print(f"[error] agent raised: {error}")
        calls = recorder.calls[start:]
        summary = summarize(q["id"], calls, recorder.context_reductions.get(q["id"], 0), args.window)
        summary["agent_error"] = error
        summaries.append(summary)
        print(
            f"[done] calls={summary['llm_calls']} max_prompt={summary['max_prompt_tokens']} "
            f"max_total={summary['max_prompt_plus_completion_tokens']} "
            f"({summary['max_pct_of_window']} % of window) length_cuts={summary['finish_reason_length']} "
            f"reductions={summary['context_reductions_logged']} -> "
            f"{'LIMITING' if summary['window_is_limiting'] else 'not limiting'}"
        )
        if summary["llm_calls"] == 0 and error:
            print("[warn] no LLM call recorded because the agent raised before calling the LLM: "
                  "this measurement is INVALID, fix the error above and rerun.")
        elif summary["llm_calls"] == 0:
            print("[warn] no LLM call recorded: the probe did not see the calls (other client class?)")

    report = {"window": args.window, "window_source": source, "summaries": summaries, "calls": recorder.calls}
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[report] written to {args.out}")
    failed = [s["question_id"] for s in summaries if s["agent_error"] or s["llm_calls"] == 0]
    if failed:
        print(f"[invalid] no usable measurement for: {failed}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
