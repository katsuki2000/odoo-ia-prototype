#!/usr/bin/env python3
"""
scripts/audit_question_resolution.py

Audit de la resolution du sujet (modeles / modules) sur les banques de
questions, sans lancer l'agent complet : seul `resolve_turn` est execute
(recherche semantique + arbitrage LLM). Meme etat et meme langue que le runner
de benchmark.

Usage:
    python scripts/audit_question_resolution.py                  # toutes les banques
    python scripts/audit_question_resolution.py CNA-Q1 MNT-Q1    # sous-ensemble par id
    python scripts/audit_question_resolution.py --bank custom_b9 --technical

Sortie : captures/question_resolution_audit.json
"""
import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from core.evaluation.preflight import BackendUnavailable, require_backends
from core.llm.llm_client import get_chat_llm
from code_intelligence.agent.resolution.turn import resolve_turn
from code_intelligence.graph import get_code_intelligence_graph
from run_bloc_n1_benchmark import build_agent_state, load_questions, read_installed_modules

REPORT_PATH = PROJECT_ROOT / "captures" / "question_resolution_audit.json"


def loadGraph(graphs, language):
    if language not in graphs:
        languages = [language] if language else None
        graphs[language] = get_code_intelligence_graph(translation_languages=languages, request_language=language)
    return graphs[language]


def auditQuestion(item, technical, graphs, llm):
    state = build_agent_state(item, technical)
    language = state.get("language")
    started = time.perf_counter()
    row = {"id": item["id"], "bank": item["bank"], "module": item["module"], "question": state["question"],
           "language": language}
    try:
        concept, _ = resolve_turn(state["question"], loadGraph(graphs, language), state, language=language, llm=llm)
        row.update(resolved=bool(concept.is_resolved), models=list(concept.resolved_models),
                   modules=list(concept.resolved_modules),
                   arbitration=concept.diagnostics.get("arbitration_outcome"))
    except Exception as error:
        row.update(resolved=False, models=[], modules=[], error=f"{type(error).__name__}: {error}")
    row["seconds"] = round(time.perf_counter() - started, 1)
    return row


def printRow(row):
    status = "OK  " if row["resolved"] else "FAIL"
    target = ", ".join(row["models"] + row["modules"]) or row.get("error", "-")
    print(f"{status} {row['id']:<9} {row['seconds']:>5}s  attendu module={row['module']:<38} -> {target}")


def main():
    parser = argparse.ArgumentParser(description="Audit de la resolution du sujet sur les banques de questions CI.")
    parser.add_argument("question_ids", nargs="*", default=None)
    parser.add_argument("--module", default=None)
    parser.add_argument("--bank", action="append", default=None)
    parser.add_argument("--technical", action="store_true", help="Questions techniques d'origine.")
    args = parser.parse_args()

    questions, _ = load_questions(args.question_ids, args.module, args.bank, read_installed_modules())
    try:
        require_backends()
    except BackendUnavailable as error:
        print(f"[SKIP] Serveur d'inference indisponible : {error}")
        return 2

    graphs = {}
    llm = get_chat_llm(temperature=0.0, max_retries=0, max_tokens=1024, model_kwargs={"parallel_tool_calls": False})
    rows = []
    for item in questions:
        row = auditQuestion(item, args.technical, graphs, llm)
        printRow(row)
        rows.append(row)

    failed = [row["id"] for row in rows if not row["resolved"]]
    print(f"\n{len(rows) - len(failed)}/{len(rows)} resolues ; echecs : {failed or 'aucun'}")
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Rapport JSON : {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
