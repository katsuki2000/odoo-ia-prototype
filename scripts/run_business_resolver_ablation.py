#!/usr/bin/env python3
"""Evaluate business-term routing from the native bank without an LLM."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from code_intelligence.agent.resolver import resolve_business_term
from code_intelligence.evaluation.resolver_metrics import summarize_evaluation
from code_intelligence.graph.loader import get_code_intelligence_graph


QUESTION_BANK_PATH = PROJECT_ROOT / "tests" / "native_n1_question_bank.json"


def _models_for_module(graph, module: str) -> set[str]:
    module_node = f"module:{module}"
    if not graph.has_node(module_node):
        return set()
    return {
        node_id.removeprefix("model:")
        for node_id, _ in graph.in_edges(module_node)
        if node_id.startswith("model:")
        and graph.edges[node_id, module_node].get("edge_type") == "DEFINED_IN"
    }


def evaluate(graph, questions: list[dict], language: str, use_static_aliases: bool) -> list[dict]:
    rows = []
    for item in questions:
        expected_models = _models_for_module(graph, item["module"])
        result = resolve_business_term(
            item["question"],
            graph,
            llm=None,
            language=language,
            use_static_aliases=use_static_aliases,
        )
        resolved_models = set(result.resolved_models)
        answered = bool(result.is_resolved and resolved_models)
        correct = bool(answered and resolved_models.intersection(expected_models))
        rows.append({
            "id": item["id"],
            "module": item["module"],
            "capability": item.get("capability"),
            "instance_id": graph.graph.get("instance_fingerprint", "source_graph"),
            "expected_module": item["module"],
            "expected_model_count": len(expected_models),
            "resolved_models": sorted(resolved_models),
            "answered": answered,
            "correct": correct,
            "source_step": result.source_step,
            "confidence": result.confidence,
            "reason": result.reason,
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", default="fr")
    parser.add_argument("--static-aliases", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    bank = json.loads(QUESTION_BANK_PATH.read_text(encoding="utf-8"))
    graph = get_code_intelligence_graph(
        translation_languages=[args.language],
        request_language=args.language,
        force_rebuild=True,
    )
    rows = evaluate(graph, bank["questions"], args.language, args.static_aliases)
    report = {
        "protocol": "business_resolver_routing",
        "language": args.language,
        "static_aliases_enabled": args.static_aliases,
        "llm_enabled": False,
        "graph_instance_fingerprint": graph.graph.get("instance_fingerprint"),
        "translation_summary": graph.graph.get("translation_summary", {}),
        "metrics": summarize_evaluation(rows),
        "results": rows,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
