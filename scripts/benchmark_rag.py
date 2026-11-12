#!/usr/bin/env python3
"""
scripts/benchmark_rag.py

Quick benchmark of the documentation RAG: the four document formats (.txt, .md, .docx, .pdf)
and out-of-scope questions.

Usage:
    python scripts/benchmark_rag.py                 # full run (retrieval + LLM answer)
    python scripts/benchmark_rag.py --retrieval     # retrieval only, no LLM
"""

import argparse
import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.schemas import source_display_title
from document_rag.retrieval.search import quick_retrieve

# Questions are in French because the indexed corpus is French.
BENCHMARK_CASES = [
    {
        "id": "TXT-01",
        "format": "TXT",
        "question": "Quel est le montant de l'indemnité kilométrique pour les déplacements en véhicule 4 roues ?",
        "expected_source": "wiki_notes_de_frais.txt",
        "expected_fact": "1 200",
    },
    {
        "id": "TXT-02",
        "format": "TXT",
        "question": "À quelle heure limite doit-on soumettre les feuilles de temps le vendredi ?",
        "expected_source": "wiki_gestion_projets_temps.txt",
        "expected_fact": "17h",
    },
    {
        "id": "MD-01",
        "format": "MD",
        "question": "Quel est le délai SLA pour la prise en charge d'un incident critique P1 sur le Helpdesk ?",
        "expected_source": "wiki_support_helpdesk_sla.md",
        "expected_fact": "30 min",
    },
    {
        "id": "MD-02",
        "format": "MD",
        "question": "Quelle commande odoo-bin avec l'option -u permet de mettre à jour le module de facturation ?",
        "expected_source": "guide_deploiement_modules_odoo.md",
        "expected_fact": "-u miro_facturation",
    },
    {
        "id": "MD-03",
        "format": "MD",
        "question": "Selon les conventions de nommage strictes d'Odoo, quel suffixe utiliser pour l'identifiant d'une vue XML d'héritage ?",
        "expected_source": "Miro - SMA, MMT, JHR, Miro K.E., Protocoles IA et Codage Défensif, v1.1, 2026-06-04.md",
        "expected_fact": "_inherit_nommodule",
    },
    {
        "id": "DOCX-01",
        "format": "DOCX",
        "question": "À partir de quel montant un bon de commande fournisseur nécessite la validation du Directeur Général ?",
        "expected_source": "guide_achats_fournisseurs.docx",
        "expected_fact": "5 000 000",
    },
    {
        "id": "DOCX-02",
        "format": "DOCX",
        "question": "Quel équipement informatique est attribué à un développeur pour le télétravail ?",
        "expected_source": "politique_teletravail_materiel.docx",
        "expected_fact": "Core i7",
    },
    {
        "id": "PDF-01",
        "format": "PDF",
        "question": "Quel est le montant total TTC et le fournisseur du bon de commande BC-2025-00142 ?",
        "expected_source": "bon_commande_fournisseur_PO2025_00142.pdf",
        "expected_fact": "39 600 000",
    },
    {
        "id": "PDF-02",
        "format": "PDF",
        "question": "Dans la procédure de clôture comptable, quelle opération est réalisée à J+3 ouvré ?",
        "expected_source": "procedure_cloture_comptable.pdf",
        "expected_fact": "rapprochement bancaire",
    },
    {
        "id": "OOS-01",
        "format": "TRAP",
        "question": "Quelle est la marque de la machine à café de la salle de pause ?",
        "expected_source": None,
        "expected_fact": None,
    },
]

# French refusal wordings: the system answers out-of-scope questions in French.
REFUSAL_MARKERS = [
    "pas de source", "non mentionné", "ne dispose pas", "hors périmètre",
    "je ne peux pas", "inconnu", "pas trouvé cette information",
]


def run_benchmark(retrieval_only: bool = False, top_k: int = 4):
    print("\n" + "=" * 80)
    print(f"RAG BENCHMARK ({'retrieval only' if retrieval_only else 'full, with generation'})")
    print("=" * 80 + "\n")

    generate_fn = None
    if not retrieval_only:
        try:
            from document_rag.generation.generate_node import generate
            generate_fn = generate
        except Exception as e:
            print(f"Cannot import generate_node ({e}). Falling back to retrieval only.\n")
            retrieval_only = True

    results = []
    total_retrieval_time = 0.0

    for idx, case in enumerate(BENCHMARK_CASES, 1):
        cid = case["id"]
        fmt = case["format"]
        q = case["question"]
        exp_src = case["expected_source"]
        exp_fact = case["expected_fact"]

        print(f"[{idx}/{len(BENCHMARK_CASES)}] [{fmt}] {q}")

        t0 = time.time()
        chunks = quick_retrieve(q, top_k=top_k)
        retrieval_duration = time.time() - t0
        total_retrieval_time += retrieval_duration

        retrieved_sources = [source_display_title(c["metadata"]) for c in chunks if c.get("metadata")]
        retrieval_ok = exp_src is None or exp_src in retrieved_sources

        # 1-based rank of the first occurrence of the expected source in the top_k results
        source_rank = (retrieved_sources.index(exp_src) + 1) if (exp_src is not None and exp_src in retrieved_sources) else None

        ans_text = ""
        gen_ok = None
        if not retrieval_only and generate_fn:
            try:
                state = {"question": q, "retrieved_chunks": chunks, "timing": {}}
                res = generate_fn(state)
                ans_text = res.get("response").answer if res.get("response") else ""
            except Exception as ex:
                ans_text = f"Generation error: {ex}"

            if exp_fact is None:
                lower_ans = ans_text.lower()
                gen_ok = any(w in lower_ans for w in REFUSAL_MARKERS)
            else:
                gen_ok = exp_fact.lower() in ans_text.lower()

        status = "PASS" if (retrieval_ok and (gen_ok is None or gen_ok)) else "FAIL"

        results.append({
            "id": cid,
            "format": fmt,
            "expected_source": exp_src,
            "retrieval_ok": retrieval_ok,
            "source_rank": source_rank,
            "retrieval_time": retrieval_duration,
            "gen_ok": gen_ok,
            "status": status,
        })

        rank_txt = f"rank {source_rank}/{len(retrieved_sources)}" if source_rank else ("n/a" if exp_src is None else f"MISSING from top {top_k}")
        print(f"       -> Sources found    : {retrieved_sources} | expected source: {rank_txt}")
        if ans_text and (status != "PASS" or exp_src is None):
            print(f"       -> Generated answer : {ans_text.replace(chr(10), ' ')[:600]}")
        print(f"       -> Retrieval time   : {retrieval_duration * 1000:.1f} ms | Result: {status}\n")

    print("=" * 80)
    print("BENCHMARK SUMMARY")
    print("=" * 80)
    print(f"{'ID':<10} | {'Format':<6} | {'Retrieval':<10} | {'Rank':<5} | {'Generation':<10} | {'Status':<8} | Expected source")
    print("-" * 80)
    for r in results:
        r_ok = "OK" if r["retrieval_ok"] else "FAIL"
        g_ok = "N/A" if r["gen_ok"] is None else ("OK" if r["gen_ok"] else "FAIL")
        src_name = r["expected_source"] or "Out of scope"
        rank = "-" if r["source_rank"] is None else str(r["source_rank"])
        print(f"{r['id']:<10} | {r['format']:<6} | {r_ok:<10} | {rank:<5} | {g_ok:<10} | {r['status']:<8} | {src_name}")

    nb_ok = sum(1 for r in results if r["status"] == "PASS")
    retrieval_accuracy = (sum(1 for r in results if r["retrieval_ok"]) / len(results)) * 100
    avg_latency = (total_retrieval_time / len(results)) * 1000

    print("-" * 80)
    print(f"Overall score        : {nb_ok}/{len(results)} passed ({nb_ok / len(results) * 100:.1f}%)")
    print(f"Retrieval accuracy   : {retrieval_accuracy:.1f}%")
    with_source = [r for r in results if r["expected_source"] is not None]
    hit_at_1 = sum(1 for r in with_source if r["source_rank"] == 1)
    median_latency = statistics.median(r["retrieval_time"] for r in results) * 1000
    print(f"Expected source at rank 1 (Hit@1): {hit_at_1}/{len(with_source)}")
    print(f"Mean retrieval latency: {avg_latency:.1f} ms / query | median: {median_latency:.1f} ms")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RAG benchmark")
    parser.add_argument("--retrieval", action="store_true", help="Run retrieval only (fast, no LLM)")
    parser.add_argument("--top-k", type=int, default=4, help="Number of chunks retrieved")
    args = parser.parse_args()

    run_benchmark(retrieval_only=args.retrieval, top_k=args.top_k)
