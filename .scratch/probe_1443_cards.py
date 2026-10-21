#!/usr/bin/env python3
"""
Sonde 1443 (jetable, hors depot) : fiches de production contre fiches E1.

Mesure, pour des questions du banc, le rang du modele attendu dans le classement
dense (embeddings), avec l'index de production (P) et avec les cartes E1 (M, MM, A).
Aucun LLM ; lecture seule du depot.

Usage, depuis la racine du depot :
    .venv/bin/python3 .scratch/probe_1443_cards.py --dry-run
    .venv/bin/python3 .scratch/probe_1443_cards.py                      # P, M, MM (rapide)
    .venv/bin/python3 .scratch/probe_1443_cards.py --systems P,M,MM,A   # A : long au 1er passage
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "scripts"))

TOP = 10
CASES = [
    ("CNA-Q1", "account.move", "echec"),
    ("CNA-Q3", "account.move", "echec"),
    ("HRL-Q2", "hr.leave", "echec"),
    ("MNT-Q4", "maintenance.equipment", "echec"),
    ("DDI-Q2", "custom.deep.document", "echec"),
    ("HRL-Q1", "hr.leave", "echec"),
    ("DDI-Q3", "custom.deep.document", "echec"),
    ("STK-Q1", "stock.quant", "echec"),
    ("PUR-Q1", "purchase.order", "temoin"),
    ("CNA-Q2", "account.move", "temoin"),
    ("SAL-Q2", "sale.order", "temoin"),
    ("MNT-Q1", "maintenance.equipment", "temoin"),
    ("ACC-Q5", "account.move", "temoin"),
]
ALL_TYPES = ("Model", "Menu", "Field", "Method", "Group", "Rule", "Button")
E1_TYPES = {"M": ("Model",), "MM": ("Model", "Menu"), "A": ALL_TYPES}


def rankOf(models, expected):
    return models.index(expected) + 1 if expected in models else None


def fmt(rank):
    return "-" if rank is None else str(rank)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--systems", default="P,M,MM")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    systems = [s.strip().upper() for s in args.systems.split(",") if s.strip()]

    from code_intelligence.graph import get_code_intelligence_graph
    from code_intelligence.agent import semantic_retrieval as sr
    from code_intelligence.evaluation.e1.cards import build_node_cards
    from run_bloc_n1_benchmark import load_questions, select_question

    graph = get_code_intelligence_graph(translation_languages=["fr"], request_language="fr")
    print(f"graphe : {graph.number_of_nodes()} noeuds")

    questions = {q["id"]: select_question(q) for q in load_questions([c[0] for c in CASES])[0]}
    prodDocs = dict(sr._model_documents(graph))
    cardsByType = {name: build_node_cards(graph, language="fr", node_types=types)
                   for name, types in E1_TYPES.items() if name in systems}

    print("\n== Fiches du modele attendu ==")
    for expected in dict.fromkeys(c[1] for c in CASES):
        print(f"[P ] {expected}: {prodDocs.get(expected, '(absent)')[:300]}")
        if "M" in cardsByType:
            card = next((c for c in cardsByType["M"] if c.object_ref == f"model:{expected}"), None)
            print(f"[M ] {expected}: {(card.text if card else '(absent)').replace(chr(10), ' / ')[:400]}")
    print("\n== Volumes ==")
    print(f"P : {len(prodDocs)} documents")
    for name, cards in cardsByType.items():
        print(f"{name:<2}: {len(cards)} cartes (~{-(-len(cards) // 64)} lots de 64 au 1er passage, cache ensuite)")
    if args.dry_run:
        return 0

    from config import settings
    from code_intelligence.evaluation.e1.dense_index import DenseCardIndex, resolve_e1_embedding_function
    from code_intelligence.evaluation.e1.projection import ModelProjector, project_candidates

    provider = resolve_e1_embedding_function()
    if provider is None:
        print("[ERREUR] Aucun fournisseur d'embeddings configure.")
        return 2
    projector = ModelProjector(graph)
    indexes = {}
    try:
        for name in systems:
            if name == "P":
                continue
            started = time.perf_counter()
            indexes[name] = DenseCardIndex.build(graph, provider, language="fr", node_types=E1_TYPES[name])
            print(f"index {name} pret en {time.perf_counter() - started:.0f}s ({len(indexes[name].cards)} cartes)")
        rows = []
        for qid, expected, kind in CASES:
            query = questions[qid]
            row = {"id": qid, "kind": kind, "expected": expected, "query": query, "ranks": {}, "top3": {}, "why": {}}
            for name in systems:
                if name == "P":
                    ranked = sr.rank_semantic_model_candidates_scored(
                        query, graph, provider, limit=10 ** 6, cache_dir=settings.SEMANTIC_INDEX_CACHE_DIR)
                    models = [model for model, _ in ranked]
                else:
                    hits = indexes[name].search(query, provider, top_k=len(indexes[name].cards))
                    models = [m.removeprefix("model:") for m in project_candidates([h.object_ref for h in hits], projector)]
                    row["why"][name] = next((f"{h.node_type}:{h.object_ref}" for h in hits
                                             if f"model:{expected}" in projector(h.object_ref)), None)
                row["ranks"][name] = rankOf(models, expected)
                row["top3"][name] = models[:3]
            rows.append(row)
    except Exception as error:
        print(f"[ERREUR] {type(error).__name__}: {str(error)[:300]}")
        print("Les vecteurs deja calcules sont conserves en cache : relancer reprend ou le calcul s'est arrete.")
        return 3

    print("\n== Rang du modele attendu (1 = premier ; '-' = absent) ==")
    print(f"{'cas':<8}{'type':<8}{'attendu':<26}" + "".join(f"{s:>6}" for s in systems))
    for row in rows:
        print(f"{row['id']:<8}{row['kind']:<8}{row['expected']:<26}" + "".join(f"{fmt(row['ranks'][s]):>6}" for s in systems))
    print(f"\n== Attendu dans le top {TOP} ==")
    for kind in ("echec", "temoin"):
        subset = [r for r in rows if r["kind"] == kind]
        print(f"{kind:<7}" + "  ".join(
            f"{s}: {sum(1 for r in subset if r['ranks'][s] and r['ranks'][s] <= TOP)}/{len(subset)}" for s in systems))
    print("\n== Top 3 et noeud porteur ==")
    for row in rows:
        print(f"{row['id']} attendu={row['expected']}")
        for s in systems:
            why = f"  via {row['why'][s]}" if row["why"].get(s) else ""
            print(f"   {s:<3} rang {fmt(row['ranks'][s]):>4}  top3={row['top3'][s]}{why}")
    with open(".scratch/probe_1443_cards.json", "w", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False, indent=2)
    print("\nJSON : .scratch/probe_1443_cards.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
