"""Run frozen cases against the system inside a process configured for one instance."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Callable, Mapping, Sequence


def read_raw(path: Path) -> dict:
    path = Path(path)
    if not path.is_file():
        return {}
    rows = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return {row["case_id"]: row for row in rows}


def ask_case(case: Mapping, credentials: Mapping, ask: Callable) -> dict:
    started = time.time()
    try:
        ask_context = {
            "question": case["question"],
            "uid": credentials["uid"],
            "api_key": credentials["api_key"],
            "language": case["user_context"]["language"],
        }
        if "group_xmlids" in credentials:
            ask_context["user_groups"] = credentials["group_xmlids"]
            ask_context["user_groups_complete"] = credentials.get("groups_complete", False)
        else:
            ask_context["user_groups"] = credentials["groups"]
        response = ask(**ask_context)
        raw = response.model_dump(mode="json")
    except Exception as error:
        raw = {"error": f"{type(error).__name__}: {error}"}
    return {"case_id": case["case_id"], "latency_seconds": round(time.time() - started, 3), "raw": raw}


def run_cases(cases: Sequence[Mapping], credentials: Mapping[str, Mapping], output: Path, ask: Callable) -> int:
    done = read_raw(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    executed = 0
    with output.open("a", encoding="utf-8") as stream:
        for case in cases:
            if case["case_id"] in done:
                continue
            row = ask_case(case, credentials[case["user_context"]["user"]], ask)
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            executed += 1
    return executed


def main() -> int:
    parser = argparse.ArgumentParser(description="Run frozen cases for one instance.")
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from core.graph.graph import query_graph

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    credentials = json.loads(args.credentials.read_text(encoding="utf-8"))
    executed = run_cases(cases, credentials, args.output, query_graph)
    print(f"{executed} cases executed -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
