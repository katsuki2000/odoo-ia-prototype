#!/usr/bin/env python3
"""
scripts/compare_observation_caps.py

A/B test (section 1072 open point (c)): does raising the character caps of
code_intelligence/agent/context.py change the answers on PUR-Q2, PUR-Q5, ACC-Q5?

NO production code is modified: the caps are monkeypatched IN MEMORY, for the
duration of this process only (PER_TOOL_OBSERVATION_CAPS is a dict read at call
time by loop.py / analysis.py / override_composer.py; MAX_TOTAL_OBSERVATION_CHARS
is a module global read by _truncate_observation_for_budget).

For every (question, condition, repeat) it records:
  - every tool observation: tool, length, truncation marker present or not
  - the final answer (verbatim), raw_tool_output length
  - LLM token usage (max prompt) to check the 32k window stays safe
Scoring stays MANUAL (todo/rules.md: no second-LLM auto-scoring). The script only
prints mechanical facts (observation sizes, markers, answer similarity).

Usage:
    .venv/bin/python3 scripts/compare_observation_caps.py
    .venv/bin/python3 scripts/compare_observation_caps.py --ids PUR-Q2 --repeat 3
    .venv/bin/python3 scripts/compare_observation_caps.py --override-cap 8000 --locks-cap 10000 --total-cap 80000
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

QUESTION_BANK = project_root / "tests" / "native_n1_question_bank.json"
DEFAULT_IDS = ["PUR-Q2", "PUR-Q5", "ACC-Q5"]


def load_questions(ids: List[str]) -> List[Dict[str, Any]]:
    data = json.loads(QUESTION_BANK.read_text(encoding="utf-8"))
    by_id = {q["id"]: q for q in data["questions"]}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise SystemExit(f"Unknown question id(s): {missing}")
    return [by_id[i] for i in ids]


def _answer_text(resp: Any) -> Any:
    if resp is None:
        return None
    return getattr(resp, "answer", None) or str(resp)


def main() -> int:
    p = argparse.ArgumentParser(description="A/B: baseline caps vs raised caps (in-memory patch).")
    p.add_argument("--ids", nargs="*", default=DEFAULT_IDS)
    p.add_argument("--repeat", type=int, default=2, help="runs per (question, condition); default 2")
    p.add_argument("--override-cap", type=int, default=6000, help="analyze_method_override_chain cap (baseline 2200)")
    p.add_argument("--locks-cap", type=int, default=8000, help="analyze_security_locks cap (baseline 3500)")
    p.add_argument("--constraints-cap", type=int, default=70000, help="analyze_data_constraints cap (baseline 45000)")
    p.add_argument("--total-cap", type=int, default=70000, help="MAX_TOTAL_OBSERVATION_CHARS (baseline 35000)")
    p.add_argument("--literal-scale", type=float, default=3.0,
                   help="multiplier applied, in the 'raised' condition, to the limit of every _truncate_observation call "
                        "reached through _truncate_observation_for_budget -- covers the ~25 literals hardcoded in "
                        "predispatch_*.py (2200/3000/4000/45000) that bypass PER_TOOL_OBSERVATION_CAPS")
    p.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "caps_ab_report.json"))
    p.add_argument("--md", default=str(Path(tempfile.gettempdir()) / "caps_ab_report.md"))
    args = p.parse_args()

    from code_intelligence.agent import context as ctxmod
    from code_intelligence.utils import _TRUNCATION_MARKER
    from core.graph.graph import code_intelligence_agent

    baseline = {
        "per_tool": dict(ctxmod.PER_TOOL_OBSERVATION_CAPS),
        "total": ctxmod.MAX_TOTAL_OBSERVATION_CHARS,
    }
    raised = {
        "per_tool": {
            **baseline["per_tool"],
            "analyze_method_override_chain": args.override_cap,
            "analyze_security_locks": args.locks_cap,
            "analyze_data_constraints": args.constraints_cap,
        },
        "total": args.total_cap,
    }
    print(f"[config] baseline={baseline}")
    print(f"[config] raised  ={raised}")

    orig_trunc = ctxmod._truncate_observation

    def apply(cond: Dict[str, Any]) -> None:
        ctxmod.PER_TOOL_OBSERVATION_CAPS.clear()
        ctxmod.PER_TOOL_OBSERVATION_CAPS.update(cond["per_tool"])
        ctxmod.MAX_TOTAL_OBSERVATION_CHARS = cond["total"]
        # _truncate_observation_for_budget resolves _truncate_observation as a global of
        # context.py at call time, so this reaches predispatch_* literals too (they import
        # _truncate_observation_for_budget, not _truncate_observation).
        if cond is raised:
            ctxmod._truncate_observation = lambda text, limit: orig_trunc(text, int(limit * args.literal_scale))
        else:
            ctxmod._truncate_observation = orig_trunc

    # Observation probe (does not alter behaviour).
    current: Dict[str, Any] = {"obs": []}
    orig_record = ctxmod.DispatchContext.record_observation

    def probe(self, tool_name, tool_args, observation, *a, **kw):
        current["obs"].append({
            "tool": tool_name,
            "args": str(tool_args)[:120],
            "chars": len(observation or ""),
            "truncated": _TRUNCATION_MARKER in (observation or ""),
        })
        return orig_record(self, tool_name, tool_args, observation, *a, **kw)

    ctxmod.DispatchContext.record_observation = probe

    # LLM usage probe (same approach as measure_context_budget.py).
    from langchain_openai import ChatOpenAI
    usage: Dict[str, Any] = {"max_prompt": 0, "calls": 0, "length_cuts": 0}
    o_sync, o_async = ChatOpenAI._generate, ChatOpenAI._agenerate

    def _rec(res):
        usage["calls"] += 1
        try:
            lo = getattr(res, "llm_output", None) or {}
            u = lo.get("token_usage") or {}
            gen = res.generations[0]
            if not u:
                m = getattr(gen.message, "usage_metadata", None) or {}
                u = {"prompt_tokens": m.get("input_tokens")}
            usage["max_prompt"] = max(usage["max_prompt"], u.get("prompt_tokens") or 0)
            if (getattr(gen, "generation_info", None) or {}).get("finish_reason") == "length":
                usage["length_cuts"] += 1
        except Exception:
            pass

    def w_sync(self, messages, *a, **kw):
        r = o_sync(self, messages, *a, **kw)
        _rec(r)
        return r

    async def w_async(self, messages, *a, **kw):
        r = await o_async(self, messages, *a, **kw)
        _rec(r)
        return r

    ChatOpenAI._generate, ChatOpenAI._agenerate = w_sync, w_async

    runs: List[Dict[str, Any]] = []
    for q in load_questions(args.ids):
        for rep in range(args.repeat):
            for name, cond in (("baseline", baseline), ("raised", raised)):
                apply(cond)
                current["obs"] = []
                usage.update({"max_prompt": 0, "calls": 0, "length_cuts": 0})
                print(f"\n[run] {q['id']} {name} #{rep + 1}")
                t0, err, out = time.time(), None, {}
                try:
                    out = code_intelligence_agent({"question": q["question"], "chat_history": []})
                except Exception as exc:
                    err = f"{type(exc).__name__}: {exc}"[:300]
                    print(f"[error] {err}")
                run = {
                    "id": q["id"], "condition": name, "repeat": rep + 1,
                    "elapsed_s": round(time.time() - t0, 1), "error": err,
                    "observations": list(current["obs"]),
                    "obs_chars_total": sum(o["chars"] for o in current["obs"]),
                    "any_truncated": any(o["truncated"] for o in current["obs"]),
                    "llm": dict(usage),
                    "response": _answer_text(out.get("response")),
                    "confidence": getattr(out.get("response"), "confidence", None),
                    "raw_tool_output_chars": len(out.get("raw_tool_output") or ""),
                }
                runs.append(run)
                Path(args.out).write_text(json.dumps({"baseline": baseline, "raised": raised, "runs": runs},
                                                     ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                print(f"[done] obs={[(o['tool'], o['chars'], 'CUT' if o['truncated'] else 'ok') for o in run['observations']]} "
                      f"max_prompt={usage['max_prompt']} llm_calls={usage['calls']} length_cuts={usage['length_cuts']}")
                ChatOpenAI._generate, ChatOpenAI._agenerate = w_sync, w_async  # keep probe installed
    apply(baseline)

    Path(args.out).write_text(json.dumps({"baseline": baseline, "raised": raised, "runs": runs},
                                         ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    # Markdown report: verbatim answers for MANUAL scoring + mechanical facts.
    md: List[str] = ["# A/B plafonds context.py (notation manuelle)\n",
                     f"baseline={baseline}\n\nraised={raised}\n"]
    qs = {q["id"]: q for q in load_questions(args.ids)}
    for qid in args.ids:
        md.append(f"\n## {qid}\n\n**Question** : {qs[qid]['question']}\n\n**Reference** : {qs[qid]['reference_answer']}\n")
        for r in [x for x in runs if x["id"] == qid]:
            md.append(f"\n### {r['condition']} #{r['repeat']} -- obs={r['obs_chars_total']} chars, "
                      f"truncated={r['any_truncated']}, max_prompt={r['llm']['max_prompt']}, "
                      f"length_cuts={r['llm']['length_cuts']}, err={r['error']}\n")
            md.append("Observations : " + ", ".join(f"{o['tool']}={o['chars']}{'(CUT)' if o['truncated'] else ''}"
                                                   for o in r["observations"]) + "\n")
            md.append("\n" + (r["response"] or "(vide)") + "\n")
        b = [x for x in runs if x["id"] == qid and x["condition"] == "baseline" and x["response"]]
        h = [x for x in runs if x["id"] == qid and x["condition"] == "raised" and x["response"]]
        if b and h:
            same_b = difflib.SequenceMatcher(None, b[0]["response"], b[-1]["response"]).ratio() if len(b) > 1 else None
            cross = difflib.SequenceMatcher(None, b[0]["response"], h[0]["response"]).ratio()
            md.append(f"\n**Similarite** : baseline#1 vs raised#1 = {cross:.2f}"
                      + (f" ; baseline#1 vs baseline#{len(b)} (bruit LLM) = {same_b:.2f}" if same_b is not None else "") + "\n")
    Path(args.md).write_text("\n".join(md), encoding="utf-8")
    print(f"\n[report] {args.out}\n[report] {args.md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
