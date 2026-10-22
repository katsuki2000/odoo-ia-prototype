#!/usr/bin/env python3
"""
scripts/run_bloc_n1_benchmark.py

Runner de benchmark des banques de questions de l'agent Code Intelligence :
toutes les banques `tests/*_question_bank.json` (modules natifs, modules
custom de l'instance, echantillon OCA). Ce script calcule seulement un signal
deterministe de couverture d'outils (expected_tools vs outils reellement
invoques) et laisse la comparaison qualitative verbatim/reference_answer a une
revue humaine.

Usage:
    python scripts/run_bloc_n1_benchmark.py                  # toutes les banques disponibles
    python scripts/run_bloc_n1_benchmark.py MNT-Q1 CNA-Q1    # sous-ensemble par id
    python scripts/run_bloc_n1_benchmark.py --bank native_n1 # une ou plusieurs banques
    python scripts/run_bloc_n1_benchmark.py --module stock   # un seul module
    python scripts/run_bloc_n1_benchmark.py --module stock MNT-Q1  # cumulable (union)
    python scripts/run_bloc_n1_benchmark.py --technical      # questions techniques d'origine

Par defaut, l'agent recoit `business_question` (francais courant, sans nom
technique, libelles de l'interface Odoo : todo/architecture.md). Les questions
dont un module requis n'est pas installe sont sautees avec un message.
Le run ne demarre pas si le serveur d'inference ou d'embeddings ne repond pas.

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
from core.evidence.source_refs import parse_code_graph_source
from core.evaluation.preflight import BackendUnavailable, require_backends
import config.settings as settings
from config.settings import LATENCY_BUDGET_P90_SECONDS
BANKS_DIR = project_root / "tests"
BANK_SUFFIX = "_question_bank.json"


def discover_banks():
    """Bank name (file name without suffix) -> path, for every bank on disk."""
    return {p.name[: -len(BANK_SUFFIX)]: p for p in sorted(BANKS_DIR.glob(f"*{BANK_SUFFIX}"))}


def open_service_session():
    """Service-account connector and its uid: the benchmark's requester."""
    from erp_data.odoo_connector import OdooConnector
    connector = OdooConnector(technical=True)
    return connector, connector.authenticate(connector.username)


def bind_requester_identity():
    """Set the requester uid and key like the API entry point, so ORM tools may read."""
    from erp_data.odoo_context import odoo_api_key_ctx, odoo_uid_ctx
    try:
        connector, uid = open_service_session()
    except Exception as error:
        print(f"[WARN] Identite de test indisponible, les outils ORM refuseront toute lecture : {error}")
        return
    odoo_uid_ctx.set(uid)
    odoo_api_key_ctx.set(connector.password)


def read_installed_modules():
    """Names of the modules installed on the target instance, or None when the
    instance cannot be queried (then no question is skipped)."""
    try:
        from code_intelligence.graph.instance_fingerprint import read_runtime_inventory
        connector, uid = open_service_session()
        modules, _ = read_runtime_inventory(connector, uid)
        return {row["name"] for row in modules}
    except Exception as error:
        print(f"[WARN] Inventaire des modules installes indisponible, aucune question sautee : {error}")
        return None


def missing_modules(item, installed_modules):
    """Modules required by a question (its own plus `requires_modules`) that are not installed."""
    required = {item["module"], *item.get("requires_modules", [])}
    return sorted(required - installed_modules) if installed_modules is not None else []


def load_questions(question_ids=None, module=None, banks=None, installed_modules=None):
    """Charge les banques demandees (toutes par defaut) et applique les filtres
    optionnels (union id/module, pas intersection -- --module stock MNT-Q1
    rejoue stock + MNT-Q1). Retourne (questions, meta) ; chaque question porte
    sa banque dans `bank` et la langue de la banque dans `language`. Avec
    `installed_modules`, les questions dont un module requis n'est pas installe
    sont sautees avec un message."""
    available = discover_banks()
    unknown_banks = set(banks or []) - set(available)
    if unknown_banks:
        print(f"[WARN] Banque(s) inconnue(s) ignoree(s): {sorted(unknown_banks)} (disponibles: {sorted(available)})")

    all_questions = []
    modules_covered = []
    for name in banks or available:
        if name not in available:
            continue
        with open(available[name], encoding="utf-8") as f:
            data = json.load(f)
        for item in data["questions"]:
            all_questions.append({**item, "bank": name, "language": data["meta"].get("language")})
        modules_covered.extend(data["meta"].get("modules_covered", []))

    ids = [q["id"] for q in all_questions]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"Ids de questions en double entre banques: {duplicates}")

    runnable = []
    for question in all_questions:
        missing = missing_modules(question, installed_modules)
        if missing:
            print(f"[SKIP] {question['id']} saute : module(s) non installe(s) {missing}.")
        else:
            runnable.append(question)
    all_questions_with_skipped, all_questions = all_questions, runnable

    meta = {"modules_covered": modules_covered}
    if not question_ids and not module:
        return all_questions, meta

    wanted_ids = set(question_ids or [])
    selected = [
        q for q in all_questions
        if q["id"] in wanted_ids or (module and q["module"] == module)
    ]

    unknown_ids = wanted_ids - {q['id'] for q in all_questions_with_skipped}
    if unknown_ids:
        print(f"[WARN] Id(s) inconnu(s) ignore(s): {sorted(unknown_ids)}")
    if module and module not in modules_covered:
        print(f"[WARN] Module '{module}' absent de modules_covered={modules_covered}")

    return selected, meta


def _extract_tools_used(sources):
    parsed = (parse_code_graph_source(getattr(s, "source", "") or "") for s in sources)
    return [ref.tool for ref in parsed if ref is not None]


def select_question(item, technical=False):
    """Wording asked to the agent: business by default, technical on request."""
    if technical:
        return item["question"]
    return item.get("business_question", item["question"])


def build_agent_state(item, technical=False):
    """Build agent input from the bank's declared personas and language."""
    state = {"question": select_question(item, technical), "chat_history": []}
    if item.get("language"):
        state["language"] = item["language"]
    principals = item.get("security_principals")
    if principals:
        state["security_principals"] = principals
    return state


def run_benchmark(question_ids=None, module=None, fresh=False, technical=False, banks=None):
    questions, meta = load_questions(question_ids, module, banks, read_installed_modules())
    if not questions:
        print("[ERROR] Aucune question ne correspond aux filtres -- rien a executer.")
        return 1

    try:
        require_backends()
    except BackendUnavailable as error:
        print(f"[SKIP] Serveur d'inference indisponible, aucun run demarre : {error}")
        return 2

    bind_requester_identity()

    print("=" * 80)
    print(" BENCHMARK RUNNER (banques de questions CI) ")
    print(f" Cible : {len(questions)} question(s)"
          + (f" (filtre id={question_ids or []}, module={module})" if (question_ids or module) else " (banques completes)"))
    print("=" * 80)

    results = []

    for item in questions:
        qid = item["id"]
        question = select_question(item, technical)
        expected_tools = item.get("expected_tools", [])

        print("\n" + "-" * 80)
        print(f"[{qid}] bank={item['bank']} module={item['module']} "
              f"capability={item['capability']} difficulty={item['difficulty']}")
        print(f"Question: {question}")
        print("-" * 80)

        record = {
            "id": qid,
            "bank": item["bank"],
            "module": item["module"],
            "capability": item["capability"],
            "difficulty": item["difficulty"],
            "question": question,
            "reference_answer": item["reference_answer"],
            "verification": item["verification"],
            "expected_tools": expected_tools,
        }

        time.sleep(2.0)  # Pacing between benchmark questions.
        start_time = time.time()
        try:
            state = build_agent_state(item, technical)
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
            missing_tools = sorted(set(expected_tools) - set(tools_used))
            tool_coverage_ok = not missing_tools

            timing_info = res.get("timing", {})
            ci_effective = timing_info.get("ci_effective_time", round(elapsed, 2))
            ci_llm_wait = timing_info.get("ci_llm_wait_time", 0.0)
            ci_hops = timing_info.get("ci_hop_count", 0)
            applied_guards = timing_info.get("ci_applied_guards", [])

            print(
                f"Reponse verbatim ({elapsed:.2f}s total | effectif {ci_effective:.2f}s | "
                f"llm_wait {ci_llm_wait:.2f}s | sauts {ci_hops}):\n{verbatim_answer}"
            )
            print(f"Outils invoques: {tools_used or '(aucun)'}")
            print(f"Gardes de post-traitement ayant modifie la reponse: {applied_guards or '(aucun)'}")
            if not tool_coverage_ok:
                print(f"[WARN] Outil(s) attendu(s) non invoque(s): {missing_tools}")

            record.update({
                "tools_used": tools_used,
                "tool_coverage_ok": tool_coverage_ok,
                "missing_tools": missing_tools,
                "verbatim": verbatim_answer,
                "elapsed_seconds": round(elapsed, 2),
                "effective_seconds": ci_effective,
                "llm_wait_seconds": ci_llm_wait,
                "hop_count": ci_hops,
                "applied_guards": applied_guards,
            })

        except Exception as e:
            print(f"[ERROR] Question echouee: {e}")
            record.update({
                "tools_used": [],
                "tool_coverage_ok": False,
                "missing_tools": expected_tools,
                "verbatim": f"ERROR: {str(e)}",
                "elapsed_seconds": 0.0,
                "effective_seconds": 0.0,
                "llm_wait_seconds": 0.0,
                "hop_count": 0,
                "applied_guards": [],
            })

        results.append(record)

    # --- Sauvegarde JSON (fusion avec l'existant si present, sauf si fresh=True) ---
    captures_dir = project_root / "captures"
    captures_dir.mkdir(exist_ok=True)

    json_report_path = captures_dir / "bloc_n1_verbatim.json"
    if not fresh and json_report_path.exists():
        try:
            with open(json_report_path, encoding="utf-8") as f:
                existing_data = json.load(f)
            merged_dict = {r["id"]: r for r in existing_data if isinstance(r, dict) and "id" in r}
            merged_dict.update({r["id"]: r for r in results})
            all_bank, _ = load_questions()
            bank_ids = {q["id"] for q in all_bank}
            results_to_save = [merged_dict[q["id"]] for q in all_bank if q["id"] in merged_dict]
            # Inclure egalement les resultats non presents dans les banques
            results_to_save.extend(r for r in merged_dict.values() if r["id"] not in bank_ids)
        except Exception as e:
            print(f"[WARN] Impossible de fusionner avec {json_report_path}: {e}")
            results_to_save = results
    else:
        results_to_save = results

    with open(json_report_path, "w", encoding="utf-8") as f:
        json.dump(results_to_save, f, indent=2, ensure_ascii=False)
    print(f"\nRapport JSON sauvegarde ({len(results_to_save)} questions): {json_report_path}")

    # --- Metriques de latence (calculees sur le run courant) ---
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

    n_errors = sum(1 for r in results_to_save if r["verbatim"].startswith("ERROR:"))
    n_tool_gaps = sum(1 for r in results_to_save if not r["tool_coverage_ok"])

    # --- Rapport Markdown (sauvegarde de toutes les questions consolidees) ---
    md_lines = [
        "# Rapport Verbatim -- benchmark des banques de questions CI\n",
        f"**Date d'execution :** {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
        "**Objectif :** rejouer les questions verite-terrain (modules natifs, modules custom, "
        "echantillon OCA) contre l'agent Code Intelligence reel et capturer la reponse "
        "verbatim pour comparaison manuelle avec `reference_answer` -- aucune notation automatique.\n",
        "---",
        "## Synthese\n",
        f"| Metrique | Valeur |",
        f"|---|---|",
        f"| Questions executees (consolidees) | {len(results_to_save)} |",
        f"| Questions rejouees ce tour | {len(results)} |",
        f"| Erreurs d'execution | {n_errors} |",
        f"| Ecarts de couverture d'outils (expected_tools non tous invoques) | {n_tool_gaps} |",
        f"| p50 latence effective (run courant) | `{p50}s` |",
        f"| p90 latence effective (run courant) | `{p90}s` (budget `{LATENCY_BUDGET_P90_SECONDS}s`, {' RESPECTE' if budget_met else ' DEPASSE'}) |",
        f"| Moyenne (run courant) | `{mean_lat}s` |",
        f"| Max (run courant) | `{max_lat}s` |",
        "\n---",
    ]

    for r in results_to_save:
        md_lines.append(
            f"\n## [{r['id']}] {r.get('bank', '?')} / {r['module']} -- {r['capability']} ({r['difficulty']})"
        )
        md_lines.append(f"**Question :** {r['question']}\n")
        md_lines.append(f"**Reponse de reference (verite-terrain) :**\n> {r['reference_answer']}\n")
        md_lines.append(f"**A verifier dans le code :** `{r['verification']}`\n")
        md_lines.append(f"**Outils attendus :** {r['expected_tools']} | **Outils invoques :** {r['tools_used']}"
                         + ("" if r["tool_coverage_ok"] else f" -- MANQUANT(S): {r['missing_tools']}"))
        md_lines.append(
            f"\n**Reponse verbatim de l'agent (Total: {r['elapsed_seconds']}s | "
            f"Effectif: {r['effective_seconds']}s | Attente LLM: {r['llm_wait_seconds']}s | "
            f"Sauts: {r['hop_count']}) :**\n"
            f"```text\n{r['verbatim']}\n```\n"
        )
        md_lines.append("---")

    md_report_path = captures_dir / "bloc_n1_verbatim.md"
    with open(md_report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
    print(f"Rapport Markdown sauvegarde: {md_report_path}")
    print("=" * 80)
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Rejoue les banques de questions CI contre l'agent Code Intelligence reel."
    )
    parser.add_argument(
        "question_ids", nargs="*", default=None,
        help="Sous-ensemble d'ids a rejouer (ex: MNT-Q1 CNA-Q1). Vide = pas de filtre par id.",
    )
    parser.add_argument(
        "--bank", nargs="+", default=None, metavar="BANK",
        help=f"Ne charge que ces banques (defaut : toutes). Disponibles : {', '.join(discover_banks())}.",
    )
    parser.add_argument(
        "--module", default=None,
        help="Ne rejoue que les questions de ce module (cumulable avec des ids explicites).",
    )
    parser.add_argument(
        "--fresh", action="store_true",
        help="Ecraser les captures precedentes sans fusionner.",
    )
    parser.add_argument(
        "--technical", action="store_true",
        help="Poser les questions techniques d'origine au lieu des questions metier.",
    )
    args = parser.parse_args()
    return run_benchmark(
        question_ids=args.question_ids or None, module=args.module,
        fresh=args.fresh, technical=args.technical, banks=args.bank,
    )


if __name__ == "__main__":
    sys.exit(main())
