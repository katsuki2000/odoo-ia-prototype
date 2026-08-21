#!/usr/bin/env python3
"""
code_intelligence/evaluation/eval_j36_expense_risk_llm.py

J36 — Sprint D élargi sur corpus custom_expense_risk_* AVEC LLM.
Envoie les 8 questions de gouvernance au vrai pipeline
code_intelligence_agent (routing → outil → synthèse LLM)
et vérifie que les keywords attendus apparaissent dans la réponse.

Usage:
    cd miro-rag
    python -m code_intelligence.evaluation.eval_j36_expense_risk_llm
"""

import json
import logging
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MIRO_RAG_DIR = BASE_DIR.parent.parent
if str(MIRO_RAG_DIR) not in sys.path:
    sys.path.insert(0, str(MIRO_RAG_DIR))

from core.graph import code_intelligence_agent, route
from core.schemas import AssistantResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DATASET_PATH = BASE_DIR / "test_dataset_expense_risk.json"
REPORT_PATH = BASE_DIR / "eval_report_j36_expense_risk.md"

# Keyword expectations per test case (searched in answer + raw_tool_output)
EXPECTED_KEYWORDS = {
    "EXP_01": ["risk_score", "alerte_conformite", "justificatif_manquant"],
    "EXP_02": ["risk_score", "alerte_conformite", "nombre_relances"],
    "EXP_03": ["justificatif_manquant", "nombre_relances", "total_amount"],
    "EXP_04": ["employee_id", "risk_score", "department_id"],
    "EXP_05": ["alerte_conformite", "employee_id"],
    "EXP_06": ["custom_expense_risk"],
    "EXP_07": ["risk_score", "total_amount"],
    "EXP_08": ["not found", "was not found", "introuvable", "n'existe pas", "non trouvé"],
}


def run_j36_llm_evaluation():
    logger.info("Loading J36 dataset from %s", DATASET_PATH)
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    test_cases = dataset["test_cases"]
    logger.info("Starting J36 LLM evaluation on %d questions...", len(test_cases))

    results = []
    total_time = 0.0
    passed = 0

    for idx, tc in enumerate(test_cases, 1):
        tc_id = tc["id"]
        question = tc["question"]
        keywords = EXPECTED_KEYWORDS.get(tc_id, [])

        logger.info("[%d/%d] %s: %s", idx, len(test_cases), tc_id, question)

        start_t = time.time()

        # Step 1: Route
        route_state = {"question": question, "retrieved_chunks": [], "timing": {}}
        route_res = route(route_state)
        route_decision = route_res.get("route")

        # Step 2: Execute code_intelligence_agent
        agent_state = {
            "question": question,
            "chat_history": [],
            "retrieved_chunks": [],
            "timing": {},
        }

        res = None
        for attempt in range(3):
            try:
                res = code_intelligence_agent(agent_state)
                break
            except Exception as e:
                err_str = str(e).lower()
                if "429" in err_str or "rate_limit" in err_str:
                    wait = 15 * (attempt + 1)
                    logger.warning("Rate limit on %s (attempt %d), waiting %ds...", tc_id, attempt + 1, wait)
                    time.sleep(wait)
                else:
                    logger.error("Error on %s: %s", tc_id, e)
                    break

        exec_time = time.time() - start_t
        total_time += exec_time

        if not res:
            res = {"response": AssistantResponse(answer="Execution failed.", sources=[], confidence=0.0)}

        resp_obj = res.get("response")
        answer_text = resp_obj.answer if resp_obj else ""
        raw_tool_output = res.get("raw_tool_output", "")
        timing_info = res.get("timing", {})
        confidence = resp_obj.confidence if resp_obj else 0.0

        # Step 3: Keyword matching
        searchable = f"{answer_text}\n{raw_tool_output}".lower()
        matched = [kw for kw in keywords if kw.lower() in searchable]
        is_passed = len(matched) > 0 or not keywords

        if is_passed:
            passed += 1

        status_icon = "✅" if is_passed else "❌"
        logger.info("  %s %s — matched %d/%d keywords — %.2fs — confidence=%.2f",
                     status_icon, tc_id, len(matched), len(keywords), exec_time, confidence)

        results.append({
            "id": tc_id,
            "question": question,
            "route": route_decision,
            "passed": is_passed,
            "matched_keywords": matched,
            "total_keywords": len(keywords),
            "exec_time_sec": round(exec_time, 3),
            "confidence": confidence,
            "answer_snippet": answer_text[:300].replace("\n", " "),
        })

        # Rate-limit cooldown between questions
        if idx < len(test_cases):
            time.sleep(3)

    accuracy = round((passed / len(test_cases)) * 100, 1) if test_cases else 0
    avg_latency = round(total_time / len(test_cases), 3) if test_cases else 0

    logger.info("=" * 60)
    logger.info("J36 LLM EVALUATION RESULTS: %d/%d PASSED (%.1f%%)", passed, len(test_cases), accuracy)
    logger.info("Average latency: %.3fs", avg_latency)
    logger.info("=" * 60)

    # Generate markdown report
    report = []
    report.append("# J36 — Évaluation LLM : Sprint D Élargi sur Corpus Expense Risk\n")
    report.append(f"**Date** : {time.strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"**Taux de succès** : **{accuracy}%** ({passed}/{len(test_cases)})")
    report.append(f"**Latence moyenne** : **{avg_latency}s**\n")
    report.append("---\n")
    report.append("## Résultats Détaillés\n")
    report.append("| ID | Question | Route | Keywords | Temps | Confiance | Statut |")
    report.append("|---|---|---|---|---|---|---|")

    for r in results:
        status = "✅ PASS" if r["passed"] else "❌ FAIL"
        kw_str = f"{len(r['matched_keywords'])}/{r['total_keywords']}"
        report.append(
            f"| `{r['id']}` | {r['question'][:60]}... | `{r['route']}` | {kw_str} | {r['exec_time_sec']}s | {r['confidence']} | {status} |"
        )

    report.append("\n---\n")
    report.append("## Extraits des Réponses LLM\n")
    for r in results:
        status = "✅" if r["passed"] else "❌"
        report.append(f"### {status} {r['id']}: {r['question'][:80]}\n")
        report.append(f"**Route** : `{r['route']}` | **Temps** : {r['exec_time_sec']}s | **Confiance** : {r['confidence']}\n")
        report.append(f"> {r['answer_snippet'][:500]}\n")

    report_text = "\n".join(report)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report_text)

    logger.info("Report written to %s", REPORT_PATH)
    return {"accuracy": accuracy, "passed": passed, "total": len(test_cases), "results": results}


if __name__ == "__main__":
    run_j36_llm_evaluation()
