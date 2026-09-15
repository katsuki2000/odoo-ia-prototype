#!/usr/bin/env python3
"""
scripts/run_bloc_n1_benchmark.py

Runner de benchmark pour le Bloc N1 
Ce script calcule seulement un signal deterministe de
couverture d'outils (expected_tools vs outils reellement invoques) et
laisse la comparaison qualitative verbatim/reference_answer a une revue
humaine 

Usage:
    python scripts/run_bloc_n1_benchmark.py                 # les 25 questions
    python scripts/run_bloc_n1_benchmark.py MNT-Q1 MNT-Q2    # sous-ensemble par id
    python scripts/run_bloc_n1_benchmark.py --module stock   # un seul module
    python scripts/run_bloc_n1_benchmark.py --module stock MNT-Q1  # cumulable (union)

Outputs (captures/) :
 - bloc_n1_verbatim.json
 - bloc_n1_verbatim.md
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

# Add project root to PYTHONPATH (miroir run_adversarial_benchmark.py)
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.graph.graph import code_intelligence_agent
from core.evidence.evidence_collector import start_evidence_collection, collect_and_clear_evidence
from config.settings import LATENCY_BUDGET_P90_SECONDS

QUESTION_BANK_PATH = project_root / "tests" / "native_n1_question_bank.json"


def load_questions(question_ids=None, module=None):
    """Charge le banc et applique les filtres optionnels (union id/module,
    pas intersection -- --module stock MNT-Q1 rejoue stock + MNT-Q1).
    Retourne (questions, meta)."""
    with open(QUESTION_BANK_PATH, encoding="utf-8") as f:
        data = json.load(f)

    all_questions = data["questions"]
    meta = data["meta"]

    if not question_ids and not module:
        return all_questions, meta

    wanted_ids = set(question_ids or [])
    selected = [
        q for q in all_questions
        if q["id"] in wanted_ids or (module and q["module"] == module)
    ]

    unknown_ids = wanted_ids - {q["id"] for q in all_questions}
    if unknown_ids:
        print(f"[WARN] Id(s) inconnu(s) ignore(s): {sorted(unknown_ids)}")
    if module and module not in meta.get("modules_covered", []):
        print(f"[WARN] Module '{module}' absent de modules_covered={meta.get('modules_covered')}")

    return selected, meta


def _extract_tools_used(sources):
    """Une SourceReference du Bloc N1/CI a pour `source` la forme
    'code_intelligence:{tool_name}:{model}' (postprocess.py::build_final_response).
    Extrait le nom d'outil brut pour le comparer a expected_tools."""
    tools = []
    for s in sources:
        src = getattr(s, "source", "") or ""
        parts = src.split(":")
        if len(parts) >= 2 and parts[0] == "code_intelligence":
            tools.append(parts[1])
    return tools


def run_benchmark(question_ids=None, module=None):
    questions, meta = load_questions(question_ids, module)
    if not questions:
        print("[ERROR] Aucune question ne correspond aux filtres -- rien a executer.")
        return

    print("=" * 80)
    print(" BLOC N1 -- BENCHMARK RUNNER (banc de questions natif) ")
    print(f" Cible : {len(questions)} question(s)"
          + (f" (filtre id={question_ids or []}, module={module})" if (question_ids or module) else " (banc complet)"))
    print("=" * 80)

    results = []

    for item in questions:
        qid = item["id"]
        mod = item["module"]
        capability = item["capability"]
        difficulty = item["difficulty"]
        question = item["question"]
        expected_tools = item.get("expected_tools", [])
        reference_answer = item["reference_answer"]
        verification = item["verification"]

        print("\n" + "-" * 80)
        print(f"[{qid}] module={mod} capability={capability} difficulty={difficulty}")
        print(f"Question: {question}")
        print("-" * 80)

        time.sleep(2.0)  # Pacing -- fenetre TPM Groq free-tier (meme discipline que Bloc 7)
        start_time = time.time()
        try:
            state = {"question": question, "chat_history": []}
            start_evidence_collection()
            try:
                res = code_intelligence_agent(state)
            finally:
                collect_and_clear_evidence()
            elapsed = time.time() - start_time

            answer_obj = res.get("response")
            if answer_obj:
                verbatim_answer = answer_obj.answer
                sources = answer_obj.sources or []
            else:
                verbatim_answer = res.get("raw_answer", "Aucune reponse")
                sources = []

            tools_used = _extract_tools_used(sources)
            tools_used_set = set(tools_used)
            expected_set = set(expected_tools)
            missing_tools = sorted(expected_set - tools_used_set)
            tool_coverage_ok = not missing_tools

            timing_info = res.get("timing", {})
            ci_effective = timing_info.get("ci_effective_time", round(elapsed, 2))
            ci_groq_wait = timing_info.get("ci_groq_wait_time", 0.0)
            ci_hops = timing_info.get("ci_hop_count", 0)

            print(
                f"Reponse verbatim ({elapsed:.2f}s total | effectif {ci_effective:.2f}s | "
                f"groq_wait {ci_groq_wait:.2f}s | sauts {ci_hops}):\n{verbatim_answer}"
            )
            print(f"Outils invoques: {tools_used or '(aucun)'}")
            if not tool_coverage_ok:
                print(f"[WARN] Outil(s) attendu(s) non invoque(s): {missing_tools}")

            results.append({
                "id": qid,
                "module": mod,
                "capability": capability,
                "difficulty": difficulty,
                "question": question,
                "reference_answer": reference_answer,
                "verification": verification,
                "expected_tools": expected_tools,
                "tools_used": tools_used,
                "tool_coverage_ok": tool_coverage_ok,
                "missing_tools": missing_tools,
                "verbatim": verbatim_answer,
                "elapsed_seconds": round(elapsed, 2),
                "effective_seconds": ci_effective,
                "groq_wait_seconds": ci_groq_wait,
                "hop_count": ci_hops,
            })

        except Exception as e:
            print(f"[ERROR] Question echouee: {e}")
            results.append({
                "id": qid,
                "module": mod,
                "capability": capability,
                "difficulty": difficulty,
                "question": question,
                "reference_answer": reference_answer,
                "verification": verification,
                "expected_tools": expected_tools,
                "tools_used": [],
                "tool_coverage_ok": False,
                "missing_tools": expected_tools,
                "verbatim": f"ERROR: {str(e)}",
                "elapsed_seconds": 0.0,
                "effective_seconds": 0.0,
                "groq_wait_seconds": 0.0,
                "hop_count": 0,
            })

    # --- Sauvegarde JSON ---
    root_dir = Path(__file__).resolve().parent.parent
    captures_dir = root_dir / "captures"
    captures_dir.mkdir(exist_ok=True)

    json_report_path = captures_dir / "bloc_n1_verbatim.json"
    with open(json_report_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nRapport JSON sauvegarde: {json_report_path}")

    # --- Metriques de latence (memes percentiles que Bloc 7) ---
    eff_latencies = [r["effective_seconds"] for r in results if r["effective_seconds"] > 0]
    if eff_latencies:
        sorted_lat = sorted(eff_latencies)
        n = len(sorted_lat)
        p50 = round(statistics.median(sorted_lat), 2)
        p90 = round(sorted_lat[min(int(n * 0.9), n - 1)], 2)
        mean_lat = round(statistics.mean(sorted_lat), 2)
        max_lat = round(max(sorted_lat), 2)
        budget_met = p90 <= LATENCY_BUDGET_P90_SECONDS
    else:
        p50 = p90 = mean_lat = max_lat = 0.0
        budget_met = True

    n_errors = sum(1 for r in results if r["verbatim"].startswith("ERROR:"))
    n_tool_gaps = sum(1 for r in results if not r["tool_coverage_ok"])

    # --- Rapport Markdown ---
    md_lines = [
        "# Rapport Verbatim -- Bloc N1 (banc de questions natif)\n",
        f"**Date d'execution :** {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
        "**Objectif :** rejouer les questions verite-terrain des 5 modules natifs "
        "(maintenance, purchase, sale, stock, account) contre l'agent Code Intelligence "
        "reel et capturer la reponse verbatim pour comparaison manuelle avec "
        "`reference_answer` -- aucune notation automatique.\n",
        "---",
        "## Synthese\n",
        f"| Metrique | Valeur |",
        f"|---|---|",
        f"| Questions executees | {len(results)} |",
        f"| Erreurs d'execution | {n_errors} |",
        f"| Ecarts de couverture d'outils (expected_tools non tous invoques) | {n_tool_gaps} |",
        f"| p50 latence effective | `{p50}s` |",
        f"| p90 latence effective | `{p90}s` (budget `{LATENCY_BUDGET_P90_SECONDS}s`, {' RESPECTE' if budget_met else ' DEPASSE'}) |",
        f"| Moyenne | `{mean_lat}s` |",
        f"| Max | `{max_lat}s` |",
        "\n---",
    ]

    for r in results:
        md_lines.append(f"\n## [{r['id']}] {r['module']} -- {r['capability']} ({r['difficulty']})")
        md_lines.append(f"**Question :** {r['question']}\n")
        md_lines.append(f"**Reponse de reference (verite-terrain) :**\n> {r['reference_answer']}\n")
        md_lines.append(f"**A verifier dans le code :** `{r['verification']}`\n")
        md_lines.append(f"**Outils attendus :** {r['expected_tools']} | **Outils invoques :** {r['tools_used']}"
                         + ("" if r["tool_coverage_ok"] else f" -- MANQUANT(S): {r['missing_tools']}"))
        md_lines.append(
            f"\n**Reponse verbatim de l'agent (Total: {r['elapsed_seconds']}s | "
            f"Effectif: {r['effective_seconds']}s | Groq wait: {r['groq_wait_seconds']}s | "
            f"Sauts: {r['hop_count']}) :**\n"
            f"```text\n{r['verbatim']}\n```\n"
        )
        md_lines.append("---")

    md_report_path = captures_dir / "bloc_n1_verbatim.md"
    with open(md_report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
    print(f"Rapport Markdown sauvegarde: {md_report_path}")
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description="Rejoue le banc de questions Bloc N1 contre l'agent Code Intelligence reel."
    )
    parser.add_argument(
        "question_ids", nargs="*", default=None,
        help="Sous-ensemble d'ids a rejouer (ex: MNT-Q1 MNT-Q2). Vide = pas de filtre par id.",
    )
    parser.add_argument(
        "--module", default=None, choices=["maintenance", "purchase", "sale", "stock", "account"],
        help="Ne rejoue que les 5 questions de ce module (cumulable avec des ids explicites).",
    )
    args = parser.parse_args()
    run_benchmark(question_ids=args.question_ids or None, module=args.module)


if __name__ == "__main__":
    main()
