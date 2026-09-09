# tests/benchmark_runner.py
"""
Benchmark runner for S4 — tests comparatifs des modèles.
Interroge chaque modèle via Groq API sur les 30 questions du jeu de test.
Mesure : temps de réponse, tokens/s, score qualitatif (1-5).
"""
import json
import time
import sys
import os
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from core.llm_client import get_chat_llm
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv()

BENCHMARK_FILE = Path(__file__).parent / "benchmark_questions.json"
RESULTS_FILE = Path(__file__).parent / "benchmark_results.json"

MODELS = [
    {
        "id": "llama-3.1-8b-instant",
        "name": "Llama 3.1 8B (Groq)",
        "provider": "groq",
        "local_equivalent": "Llama 3.1 8B Q4 (~6 Go VRAM)",
    },
    {
        "id": "meta-llama/llama-4-scout-17b-16e-instruct",
        "name": "Llama 4 Scout 17B (Groq)",
        "provider": "groq",
        "local_equivalent": "N/A — testé pour référence qualité max",
    },
]

SYSTEM_PROMPTS = {
    "documentaire": (
        "Tu es un assistant spécialisé dans la documentation Odoo 17 et les procédures internes "
        "de MIRO KE. Réponds en français à la question en te basant uniquement sur les connaissances "
        "que tu as de la documentation Odoo. Si tu n'es pas sûr, indique-le."
    ),
    "code_source": (
        "Tu es un assistant spécialisé dans le code source Odoo 17. Réponds en français à la question "
        "sur la structure du code, les modèles et les modules Odoo."
    ),
    "erp_chiffre": (
        "Tu es un assistant spécialisé dans les données ERP d'Odoo. Réponds en français avec des "
        "chiffres précis. Base-toi sur les données disponibles."
    ),
    "hors_perimetre": (
        "Tu es un assistant spécialisé uniquement dans les questions relatives à Odoo, à l'ERP, "
        "et aux procédures internes de MIRO KE. Si la question ne concerne pas ces sujets, "
        "réponds poliment que tu ne peux pas répondre et invite à reformuler."
    ),
}

def load_benchmark():
    with open(BENCHMARK_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def get_system_prompt(category):
    return SYSTEM_PROMPTS.get(category, SYSTEM_PROMPTS["documentaire"])

def score_answer(question, answer, max_score=5):
    """Score qualitatif (1-5) basé sur la présence des éléments attendus."""
    answer_lower = answer.lower()
    expected = question.get("expected_answer_contains", [])

    if not expected:
        expected = [question.get("expected_behavior", "refus")]

    found = sum(1 for kw in expected if kw.lower() in answer_lower)
    total = len(expected)

    if total == 0:
        return 3

    ratio = found / total

    if ratio >= 0.8:
        return min(5, max_score)
    elif ratio >= 0.5:
        return 4
    elif ratio >= 0.25:
        return 3
    elif found > 0:
        return 2
    else:
        return 1

def run_benchmark():
    benchmark = load_benchmark()
    questions = benchmark["questions"]
    results = {
        "meta": {
            "date": "2026-07-03",
            "environment": "Groq API (cloud, free tier)",
            "benchmark_file": str(BENCHMARK_FILE),
        },
        "models": {},
    }

    for model_cfg in MODELS:
        model_id = model_cfg["id"]
        model_name = model_cfg["name"]
        print(f"\n{'='*60}")
        print(f"Benchmarking: {model_name}")
        print(f"{'='*60}")

        llm = get_chat_llm(
            model=model_id,
            temperature=0.1,
            max_tokens=1024,
        )

        model_results = []
        total_time = 0
        total_tokens = 0
        total_score = 0

        for i, q in enumerate(questions):
            qid = q["id"]
            cat = q["category"]
            question = q["question"]

            system_prompt = get_system_prompt(cat)
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=question),
            ]

            start = time.time()
            try:
                response = llm.invoke(messages)
                elapsed = time.time() - start
                answer_text = response.content

                usage = response.usage_metadata if hasattr(response, 'usage_metadata') else {}
                input_tokens = usage.get('input_tokens', 0) if isinstance(usage, dict) else 0
                output_tokens = usage.get('output_tokens', 0) if isinstance(usage, dict) else 0
                token_count = input_tokens + output_tokens

                score_val = score_answer(q, answer_text)

                total_time += elapsed
                total_tokens += token_count
                total_score += score_val

                print(f"  [{i+1:2d}/{len(questions)}] {qid} ({cat:15s}) | score={score_val}/5 | {elapsed:.1f}s | {token_count} tokens")

                model_results.append({
                    "id": qid,
                    "category": cat,
                    "question": question,
                    "answer": answer_text,
                    "score": score_val,
                    "time_seconds": round(elapsed, 2),
                    "tokens": token_count,
                    "expected_keywords_found": [kw for kw in q.get("expected_answer_contains", []) if kw.lower() in answer_text.lower()],
                })

            except Exception as e:
                elapsed = time.time() - start
                print(f"  [{i+1:2d}/{len(questions)}] {qid} ({cat:15s}) | ERROR: {e}")
                model_results.append({
                    "id": qid,
                    "category": cat,
                    "question": question,
                    "answer": f"[ERREUR] {str(e)}",
                    "score": 0,
                    "time_seconds": round(elapsed, 2),
                    "tokens": 0,
                    "error": str(e),
                })

        avg_time = total_time / len(questions) if questions else 0
        avg_score = total_score / len(questions) if questions else 0
        tokens_per_sec = total_tokens / total_time if total_time > 0 else 0

        print(f"\n  Résultats {model_name}:")
        print(f"  Score moyen: {avg_score:.2f}/5")
        print(f"  Temps moyen: {avg_time:.1f}s")
        print(f"  Tokens total: {total_tokens}")
        print(f"  Tokens/s: {tokens_per_sec:.1f}")

        results["models"][model_id] = {
            "name": model_name,
            "provider": model_cfg["provider"],
            "local_equivalent": model_cfg.get("local_equivalent", ""),
            "avg_score": round(avg_score, 2),
            "avg_time_seconds": round(avg_time, 2),
            "total_tokens": total_tokens,
            "tokens_per_second": round(tokens_per_sec, 1),
            "total_score": total_score,
            "max_possible_score": len(questions) * 5,
            "results": model_results,
        }

    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"Résultats sauvegardés dans {RESULTS_FILE}")
    print(f"{'='*60}")

    print_summary(results)

def print_summary(results):
    print(f"\n{'='*60}")
    print("RÉSUMÉ DU BENCHMARK")
    print(f"{'='*60}")
    for model_id, data in results["models"].items():
        print(f"\n{data['name']}:")
        print(f"  Score moyen:       {data['avg_score']}/5")
        print(f"  Temps moyen/rép.:  {data['avg_time_seconds']}s")
        print(f"  Tokens/s:          {data['tokens_per_second']}")
        print(f"  Score total:       {data['total_score']}/{data['max_possible_score']}")

        cat_scores = {}
        for r in data["results"]:
            cat = r["category"]
            if cat not in cat_scores:
                cat_scores[cat] = {"total": 0, "count": 0}
            cat_scores[cat]["total"] += r["score"]
            cat_scores[cat]["count"] += 1

        print(f"  Scores par catégorie:")
        for cat, s in cat_scores.items():
            print(f"    {cat:20s}: {s['total']}/{s['count']*5} (moy: {s['total']/s['count']:.1f}/5)")

if __name__ == "__main__":
    run_benchmark()
