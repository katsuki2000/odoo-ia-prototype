#!/usr/bin/env python3
"""
scripts/run_adversarial_benchmark.py

Automated Benchmark Runner for Story S1.3 (Agile Sprint 1):
Executes all test questions from the README of ground truth against the Code Intelligence agent,
recording verbatim answers, cited sources, tools invoked, and qualitative evaluation.

Outputs:
 - Console verbatim output
 - Markdown Benchmark Report: todo/verbatim_responses_sprint1.md
 - JSON Evaluation Report: todo/verbatim_responses_sprint1.json
"""

import sys
import json
import time
from pathlib import Path

# Add project root & miro-rag to PYTHONPATH
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "miro-rag"))

from rag.graph import code_intelligence_agent, _get_admin_rpc_client


def _resolve_bloc7_test_group_ids():
    """
    Bloc 7 harness fix (2026-08-04): Q6.1/Q6.2 describe a requester who is
    member of both / neither of group_avoir_regional and group_avoir_national
    (custom_credit_note_visibility_rules), but the benchmark never actually
    passed any user_groups into the pipeline -- state['user_groups'] was
    always absent, so code_intelligence_agent() resolved it to [] for every
    question, and Q6.1/Q6.2 silently tested the exact same (ungrouped)
    scenario. Resolve the two groups' real DB ids here so both questions can
    be run as the requester the ground truth actually describes.

    Reuses rag.graph's lazy admin RPC singleton (_get_admin_rpc_client)
    instead of opening a second admin connection -- this is the same
    pure static-metadata lookup (group xml_id never depends on who's
    asking) that _resolve_user_group_xmlids() already does internally,
    just in the reverse direction (xml_id -> DB id).
    """
    client, admin_uid = _get_admin_rpc_client()
    records = client.execute_kw(
        admin_uid, "ir.model.data", "search_read",
        [[("module", "=", "custom_credit_note_visibility_rules"),
          ("name", "in", ["group_avoir_regional", "group_avoir_national"])]],
        {"fields": ["name", "res_id"]},
    )
    by_name = {r["name"]: r["res_id"] for r in records}
    return by_name.get("group_avoir_regional"), by_name.get("group_avoir_national")

BENCHMARK_QUESTIONS = [
    {
        "id": "Q1.1",
        "category": "1. Cascade avoirs (Standard)",
        "question": "Qui a le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) ?",
        "expected": "Niveau 1: Groupe account.group_account_manager (>5000€). Niveau 2: Directeur régional (N+2) notifié (>20000€, code Python). Risque: N+2 non géré si vide."
    },
    {
        "id": "Q1.2",
        "category": "1. Cascade avoirs (VIP)",
        "question": "Qui a le droit d'approuver un avoir pour un client VIP ?",
        "expected": "Bypass total pour avoir_vip_exempt = True. Piège: super().action_valider_avoir() rappelé sur tout le recordset à la fin."
    },
    {
        "id": "Q2.1",
        "category": "2. Congés (Message d'erreur)",
        "question": "Pourquoi je n'arrive pas à valider ma demande de congé alors que j'ai coché 'urgente' ?",
        "expected": "Message d'erreur exact: 'Une demande urgente dépassant le solde doit être validée par le N+2 ou un responsable RH.'"
    },
    {
        "id": "Q3.1",
        "category": "3. Demande d'achat (Bypass e-mails)",
        "question": "Qui a le droit d'approuver une demande d'achat de 15 000€ ?",
        "expected": "Le groupe purchase_manager ne suffit pas >10000€. Seuls logins dans _VALIDATEURS_EXCEPTIONNELS (direction@societe.com, daf@societe.com) peuvent valider."
    },
    {
        "id": "Q4.1",
        "category": "4. Asset loan (Référence croisée)",
        "question": "Comment faire une demande de mise à disposition de matériel, et y a-t-il des conditions particulières ?",
        "expected": "Nécessite demande_achat_liee_id. Si >2000€, bénéficiaire != demandeur (séparation des rôles)."
    },
    {
        "id": "Q5.1",
        "category": "5. Actions serveur (Data / sudo)",
        "question": "Est-ce que tous les avoirs fournisseurs passent par les mêmes règles d'approbation ?",
        "expected": "NON: fournisseurs ID 42, 108, 231 auto-validés via ir.actions.server avec sudo() contournant les règles standard."
    },
    {
        "id": "Q6.1",
        "category": "6. ir.rule ET/OU (Deux groupes)",
        "question": "Un utilisateur membre à la fois du groupe régional et du groupe national peut-il voir un avoir de 80 000€ ?",
        "expected": "OUI: Règles de groupe en OU. La règle nationale (illimitée) l'emporte sur le plafond 50k€ régional.",
        "user_groups": "BOTH"
    },
    {
        "id": "Q6.2",
        "category": "6. ir.rule ET/OU (Aucun groupe)",
        "question": "Un utilisateur qui n'appartient à AUCUN des deux groupes (ni régional, ni national) peut-il voir ce même avoir de 80 000€ ?",
        "expected": "OUI: Ni l'une ni l'autre règle ne s'applique. Soumis uniquement à la règle globale (société) sans limite de montant.",
        "user_groups": "NONE"
    },
    {
        "id": "Q9.1",
        "category": "9. Incertitude (getattr dynamic)",
        "question": "Qui peut valider une demande de remboursement de frais dans le module custom_expense_reimbursement_indirect ?",
        "expected": "Point de contrôle dynamique (getattr/_g_q7) repéré dans action_valider mais NON CLASSIFIÉ avec certitude. Proposer pour revue manuelle avec source fichier+ligne."
    }
]


def run_benchmark():
    print("=" * 80)
    print(" CODE INTELLIGENCE — AUTOMATED BENCHMARK RUNNER (SPRINT 2)")
    print(" Target: 9 Adversarial Test Questions")
    print("=" * 80)

    # NOTE (2026-07-29): run_pipeline()/set_graph_ref() ici étaient du code mort --
    # code_intelligence_agent() (rag/graph.py) appelle get_code_intelligence_graph()
    # puis set_graph_ref() lui-même à CHAQUE question, ce qui écrasait silencieusement
    # ce graphe de 9 modules custom_* avec le graphe complet (fake_data/code + miro_ai
    # + custom_*, ~3775 nœuds) avant que la première question ne soit posée.
    # Le benchmark a donc toujours tourné sur le graphe complet, jamais sur celui-ci --
    # supprimé pour éviter la confusion (cf. logs Sprint 2, 2026-07-29).

    results = []

    # Bloc 7 harness fix: resolve the real group DB ids once, so Q6.1/Q6.2
    # can be run as the requester their ground truth actually describes
    # instead of silently falling back to an empty (ungrouped) requester.
    try:
        region_id, national_id = _resolve_bloc7_test_group_ids()
        if region_id is None or national_id is None:
            print(f"[WARN] Could not resolve group ids (region={region_id}, national={national_id}). "
                  f"Q6.1/Q6.2 will run as an ungrouped requester.")
        group_map = {
            "BOTH": [g for g in (region_id, national_id) if g is not None],
            "NONE": [],
        }
    except Exception as e:
        print(f"[WARN] Group id resolution failed ({e}). Q6.1/Q6.2 will run as an ungrouped requester.")
        group_map = {"BOTH": [], "NONE": []}

    for item in BENCHMARK_QUESTIONS:
        qid = item["id"]
        category = item["category"]
        question = item["question"]
        expected = item["expected"]
        user_groups = group_map.get(item.get("user_groups"), [])

        print("\n" + "-" * 80)
        print(f"[{qid}] Category: {category}")
        print(f"Question: {question}")
        if item.get("user_groups"):
            print(f"Requester groups: {item['user_groups']} -> DB ids {user_groups}")
        print("-" * 80)

        start_time = time.time()
        try:
            state = {"question": question, "chat_history": [], "user_groups": user_groups}
            res = code_intelligence_agent(state)
            elapsed = time.time() - start_time

            answer_obj = res.get("response")
            if answer_obj:
                verbatim_answer = answer_obj.answer
                sources = [s.source for s in answer_obj.sources] if answer_obj.sources else []
            else:
                verbatim_answer = res.get("raw_answer", "Aucune réponse")
                sources = []

            print(f"Verbatim Response ({elapsed:.2f}s):\n{verbatim_answer}")

            results.append({
                "id": qid,
                "category": category,
                "question": question,
                "expected": expected,
                "verbatim": verbatim_answer,
                "sources": sources,
                "elapsed_seconds": round(elapsed, 2)
            })

        except Exception as e:
            print(f"[ERROR] Query failed: {e}")
            results.append({
                "id": qid,
                "category": category,
                "question": question,
                "expected": expected,
                "verbatim": f"ERROR: {str(e)}",
                "sources": [],
                "elapsed_seconds": 0.0
            })

    # Save outputs
    root_dir = Path(__file__).resolve().parent.parent
    todo_dir = root_dir / "todo"
    todo_dir.mkdir(exist_ok=True)

    json_report_path = todo_dir / "verbatim_responses_sprint2.json"
    with open(json_report_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nSaved JSON verbatim report to: {json_report_path}")

    # Generate Markdown summary
    md_lines = [
        "# Rapport Verbatim — Test Adversarial (Sprint 2 / End-to-End Benchmark)\n",
        f"**Date d'exécution :** {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
        "**Objectif :** Poser les questions test du README à l'agent Code Intelligence et mesurer les réponses verbatim après résolution des verrous Sprint 2.\n",
        "---",
    ]

    for r in results:
        md_lines.append(f"\n## [{r['id']}] {r['category']}")
        md_lines.append(f"**Question :** {r['question']}\n")
        md_lines.append(f"**Vérité Terrain attendue :**\n> {r['expected']}\n")
        md_lines.append(f"**Réponse Verbatim de l'agent ({r['elapsed_seconds']}s) :**\n```text\n{r['verbatim']}\n```\n")
        md_lines.append("---")

    md_report_path = todo_dir / "verbatim_responses_sprint2.md"
    with open(md_report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
    print(f"Saved Markdown verbatim report to: {md_report_path}")
    print("=" * 80)


if __name__ == "__main__":
    run_benchmark()
