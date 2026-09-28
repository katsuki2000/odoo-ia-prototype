#!/usr/bin/env python3
"""
Compare synthesis models on frozen tool evidence (todo/contexte.txt, section 985).

    python scripts/run_synthesis_model_bench.py capture [IDS...] [--module stock]
    python scripts/run_synthesis_model_bench.py replay --model ollama:gpt-oss:20b --model ollama:qwen3:14b

capture runs the real agent once per question with the configured LLM and
freezes the exact synthesis prompt. replay sends those frozen prompts to each
model, N samples each, and scores the answers deterministically. Without
--model, replay uses LOCAL_LLM_MODEL from the environment.
"""

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.evaluation.synthesis_bench import (
    FrozenCase,
    ModelSpec,
    SynthesisPromptRecorder,
    default_model_specs,
    load_cases,
    render_markdown,
    replay,
    save_case,
    summarize,
)

DEFAULT_FROZEN_DIR = project_root / "captures" / "frozen_evidence"
DEFAULT_REPORT_STEM = project_root / "captures" / "synthesis_model_bench"


def capture(args) -> None:
    from run_bloc_n1_benchmark import build_agent_state, load_questions
    from core.evidence.evidence_collector import collect_and_clear_evidence, start_evidence_collection
    from core.graph.graph import code_intelligence_agent

    questions, _ = load_questions(args.question_ids or None, args.module)
    for item in questions:
        recorder = SynthesisPromptRecorder()
        start_evidence_collection()
        try:
            with recorder.attached():
                code_intelligence_agent(build_agent_state(item))
        finally:
            collect_and_clear_evidence()
        if recorder.last_prompt is None:
            print(f"[SKIP] {item['id']}: no synthesis call (answered without the synthesis step)")
            continue
        path = save_case(args.dir, FrozenCase(
            id=item["id"], question=item["question"],
            synthesis_prompt=recorder.last_prompt, reference_answer=item["reference_answer"],
        ))
        print(f"[OK] {item['id']} -> {path}")


def run_replay(args) -> None:
    cases = load_cases(args.dir, args.question_ids or None)
    if not cases:
        sys.exit(f"No frozen case found in {args.dir} -- run the capture step first.")
    specs = [ModelSpec.parse(raw) for raw in args.model] if args.model else default_model_specs()

    results = replay(cases, specs, args.samples, args.temperature, args.base_url, args.allow_thinking)
    summary = summarize(results)

    stem = Path(args.report_stem)
    stem.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": summary,
        "samples": [{**asdict(r), "score": asdict(r.score)} for r in results],
    }
    stem.with_suffix(".json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    stem.with_suffix(".md").write_text(render_markdown(results, summary), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Reports written to {stem}.json / .md")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, default=DEFAULT_FROZEN_DIR, help="Frozen evidence directory.")
    sub = parser.add_subparsers(dest="command", required=True)

    cap = sub.add_parser("capture", help="Freeze the synthesis prompt of bank questions.")
    cap.add_argument("question_ids", nargs="*")
    cap.add_argument("--module", choices=["maintenance", "purchase", "sale", "stock", "account"])
    cap.set_defaults(handler=capture)

    rep = sub.add_parser("replay", help="Replay frozen prompts against one or more models.")
    rep.add_argument("question_ids", nargs="*")
    rep.add_argument("--model", action="append", help="[provider:]model, repeatable (e.g. ollama:qwen3:14b).")
    rep.add_argument("--samples", type=int, default=3)
    rep.add_argument("--temperature", type=float, default=0.0)
    rep.add_argument("--base-url", default=None, help="OpenAI-compatible endpoint; defaults to LOCAL_LLM_BASE_URL.")
    rep.add_argument("--allow-thinking", action="store_true", help="Do not append /no_think for Qwen3 models.")
    rep.add_argument("--report-stem", default=str(DEFAULT_REPORT_STEM))
    rep.set_defaults(handler=run_replay)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
