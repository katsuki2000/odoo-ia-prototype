"""
coverage_report.py

Mesure le taux de couverture des données(labels métier) sur le graphe
de connaissances déjà généré : knowledge_graph.json.

Usage :
    python3 coverage_report.py /chemin/vers/knowledge_graph.json
"""

import json
import sys
from pathlib import Path

import networkx as nx


def load_graph(filepath: Path) -> nx.DiGraph:
    data = json.loads(filepath.read_text(encoding="utf-8"))
    return nx.node_link_graph(data)


def report(G: nx.DiGraph) -> None:
    models = [n for n, d in G.nodes(data=True) if d.get("node_type") == "Model"]
    fields = [n for n, d in G.nodes(data=True) if d.get("node_type") == "Field"]
    menus = [n for n, d in G.nodes(data=True) if d.get("node_type") == "Menu"]

    models_with_desc = [n for n in models if G.nodes[n].get("description")]
    fields_with_label = [n for n in fields if G.nodes[n].get("label")]
    menus_with_model = [
        n for n in menus
        if any(G.edges[n, t].get("edge_type") == "OPENS_MODEL" for t in G.successors(n))
    ]
    unresolved_menus = [n for n in menus if n not in menus_with_model]
    # Split unresolved menus: no action at all (folder menu, expected) vs has an
    # action reference that failed to resolve (real gap worth investigating).
    unresolved_no_action = [n for n in unresolved_menus if not G.nodes[n].get("action_ref")]
    unresolved_with_action = [n for n in unresolved_menus if G.nodes[n].get("action_ref")]

    def pct(part: list, whole: list) -> str:
        if not whole:
            return "n/a (0 nœud)"
        return f"{len(part)}/{len(whole)} ({100 * len(part) / len(whole):.1f}%)"

    print("=== Couverture B0 (labels métier -> fuzzy-matching) ===")
    print(f"Model.description renseigné  : {pct(models_with_desc, models)}")
    print(f"Field.label renseigné        : {pct(fields_with_label, fields)}")
    print(f"Menu -> OPENS_MODEL résolu    : {pct(menus_with_model, menus)}")
    print(f"  dont sans action (dossier, normal) : {len(unresolved_no_action)}")
    print(f"  dont AVEC action mais non résolue  : {len(unresolved_with_action)}  <- à vérifier")

    if unresolved_with_action:
        print(f"\n{len(unresolved_with_action)} menu(s) avec action non résolue — échantillon :")
        for n in unresolved_with_action[:15]:
            d = G.nodes[n]
            print(f"  - {n} (name={d.get('name')!r}, action_ref={d.get('action_ref')!r})")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 coverage_report.py /chemin/vers/knowledge_graph.json")
        sys.exit(1)

    graph_path = Path(sys.argv[1])
    if not graph_path.exists():
        print(f"Fichier introuvable : {graph_path}")
        sys.exit(1)

    G = load_graph(graph_path)
    report(G)
