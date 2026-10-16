#!/usr/bin/env python3
"""Evaluate business-term routing from the native bank, optionally with LLM arbitration."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from code_intelligence.agent.matching import _fuzzy_match_graph
from code_intelligence.agent.resolver import (
    WIDENED_CANDIDATE_LIMIT,
    WIDENED_CANDIDATE_THRESHOLD,
    resolve_business_term,
)
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
        and graph.edges[node_id, module_node].get("role", "declares") == "declares"
    }


def _modules_for_candidates(graph, models: list[str]) -> list[str]:
    modules = []
    for model in models:
        model_node = f"model:{model}"
        if not graph.has_node(model_node):
            continue
        for successor in graph.successors(model_node):
            edge = graph.edges[model_node, successor]
            if (
                edge.get("edge_type") != "DEFINED_IN"
                or edge.get("role", "declares") != "declares"
            ):
                continue
            module = successor.removeprefix("module:")
            if module not in modules:
                modules.append(module)
    return modules


def evaluate(graph, questions: list[dict], language: str, llm=None) -> list[dict]:
    rows = []
    for item in questions:
        expected_models = _models_for_module(graph, item["module"])
        result = resolve_business_term(
            item["question"],
            graph,
            llm=llm,
            language=language,
        )
        candidate_models = list(result.resolved_models)
        if not result.is_resolved:
            fuzzy_candidates = _fuzzy_match_graph(item["question"], graph)
            if not fuzzy_candidates:
                fuzzy_candidates = _fuzzy_match_graph(
                    item["question"],
                    graph,
                    threshold=WIDENED_CANDIDATE_THRESHOLD,
                    limit=WIDENED_CANDIDATE_LIMIT,
                )
            candidate_models = [model for model, _score in fuzzy_candidates]
        candidate_modules = _modules_for_candidates(graph, candidate_models)
        candidate_domain_evaluable = not result.is_resolved
        candidate_domain_rank = None
        if candidate_domain_evaluable and item["module"] in candidate_modules:
            candidate_domain_rank = candidate_modules.index(item["module"]) + 1
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
            "candidate_models": candidate_models,
            "candidate_modules": candidate_modules,
            "candidate_domain_rank": candidate_domain_rank,
            "candidate_domain_evaluable": candidate_domain_evaluable,
            "answered": answered,
            "correct": correct,
            "source_step": result.source_step,
            "confidence": result.confidence,
            "reason": result.reason,
            "semantic_retrieval": result.diagnostics.get("semantic_retrieval", "not_used"),
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", default="fr")
    parser.add_argument("--use-llm", action="store_true",
                        help="Enable bounded LLM arbitration on tied candidates.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    llm = None
    if args.use_llm:
        from core.llm.llm_client import get_chat_llm
        llm = get_chat_llm(temperature=0.0, max_retries=0)

    bank = json.loads(QUESTION_BANK_PATH.read_text(encoding="utf-8"))
    graph = get_code_intelligence_graph(
        translation_languages=[args.language],
        request_language=args.language,
        force_rebuild=True,
    )
    rows = evaluate(graph, bank["questions"], args.language, llm=llm)
    report = {
        "protocol": "business_resolver_routing",
        "language": args.language,
        "llm_enabled": args.use_llm,
        "graph_instance_fingerprint": graph.graph.get("instance_fingerprint"),
        "graph_instance_fingerprint_data": graph.graph.get("instance_fingerprint_data", {}),
        "translation_summary": graph.graph.get("translation_summary", {}),
        "runtime_translation_summary": graph.graph.get("runtime_translation_summary", {}),
        "semantic_retrieval_summary": dict(Counter(row["semantic_retrieval"] for row in rows)),
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
