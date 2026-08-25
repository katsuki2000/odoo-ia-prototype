"""
test_resolver_fuzzy_vs_alias.py

J1/J2 — Vérifie si le fuzzy-matching (Step 1) produit des faux-positifs qui
court-circuitent la table d'alias (Step 2) avant qu'elle n'ait sa chance.

Usage:
    python3 test_resolver_fuzzy_vs_alias.py /home/user/odoo-17.0/addons/knowledge_graph/knowledge_graph.json
"""
import sys
import json
import networkx as nx
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from code_intelligence.business_resolver import (
    resolve_business_term, _fuzzy_match_graph, BUSINESS_ALIASES, _build_fuzzy_index
)

# Requêtes tirées directement des 9 questions adversariales + variantes courtes
# qui stressent le cas "terme court, risque de faux-positif fuzzy"
TEST_QUERIES = [
    "avoir",
    "avoirs",
    "vip",
    "client vip",
    "mise à disposition",
    "mise a disposition",
    "matériel",
    "congé",
    "congés",
    "demande d'achat",
    "demande de mise à disposition de matériel",
    "remboursement de frais",
    "note de frais",
    "régional",
    "national",
    # Questions complètes, telles que posées dans le benchmark
    "Qui a le permission d'approuver un avoir de 25 000€ pour un client normal (pas VIP) ?",
    "Pourquoi je n'arrive pas à valider ma demande de congé alors que j'ai coché 'urgente' ?",
    "Qui a le permission d'approuver une demande d'achat de 15 000€ ?",
    "Comment faire une demande de mise à disposition de matériel, et y a-t-il des conditions particulières ?",
    "Qui peut valider une demande de remboursement de frais dans le module custom_expense_reimbursement_indirect ?",
]


def load_graph(filepath: Path) -> nx.DiGraph:
    data = json.loads(filepath.read_text(encoding="utf-8"))
    return nx.node_link_graph(data)


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 test_resolver_fuzzy_vs_alias.py /chemin/vers/knowledge_graph.json")
        sys.exit(1)

    G = load_graph(Path(sys.argv[1]))
    print(f"Graphe chargé : {G.number_of_nodes()} nœuds, {G.number_of_edges()} arêtes\n")

    index = _build_fuzzy_index(G)
    print(f"Index fuzzy construit : {len(index)} entrées (Model.description / Field.label / Menu.name)\n")

    print("=" * 100)
    print(" COMPARAISON FUZZY (Step 1) vs ALIAS STATIQUE (Step 2), PAR REQUÊTE")
    print("=" * 100)

    mismatches = []
    alias_shadowed = []

    for query in TEST_QUERIES:
        clean = query.lower().strip()

        fuzzy_results = _fuzzy_match_graph(clean, G)

        alias_matched_terms = [a for a in BUSINESS_ALIASES if a in clean]
        alias_targets = []
        for a in alias_matched_terms:
            alias_targets.extend(BUSINESS_ALIASES[a])
        alias_targets = list(dict.fromkeys(alias_targets))  # dedup, ordre préservé

        final = resolve_business_term(query, G)

        print(f"\nRequête : {query!r}")
        print(f"  Fuzzy (Step 1)  : {fuzzy_results if fuzzy_results else '(aucun match >= seuil)'}")
        print(f"  Alias (Step 2)  : termes={alias_matched_terms} -> cibles={alias_targets}")
        print(f"  Résultat final  : source={final.source_step}, "
              f"models={final.resolved_models}, modules={final.resolved_modules}, "
              f"confidence={final.confidence}, resolved={final.is_resolved}")

        # Signal 1 : le fuzzy a matché AVANT la table d'alias, et le résultat
        # fuzzy ne contient AUCUNE des cibles que l'alias aurait donné ->
        # l'alias a été court-circuité par un résultat potentiellement non pertinent.
        if fuzzy_results and alias_targets:
            fuzzy_models = {m for m, _ in fuzzy_results}
            if not (fuzzy_models & set(alias_targets)):
                alias_shadowed.append((query, fuzzy_results, alias_targets))

        # Signal 2 : le résultat final ne contient aucune des cibles attendues
        # par la table d'alias alors qu'un alias matchait bien le texte -- un
        # vrai risque de régression fonctionnelle sur des requêtes déjà connues.
        if alias_targets and not (set(final.resolved_models) & set(alias_targets)):
            mismatches.append((query, alias_targets, final.resolved_models))

    print("\n" + "=" * 100)
    print(" VERDICT")
    print("=" * 100)

    if alias_shadowed:
        print(f"\n  {len(alias_shadowed)} requête(s) où le fuzzy-matching a produit un résultat "
              f"SANS RAPPORT avec ce que la table d'alias aurait donné (court-circuit potentiel) :")
        for q, fz, al in alias_shadowed:
            print(f"  - {q!r}")
            print(f"      fuzzy -> {fz}")
            print(f"      alias attendait -> {al}")
    else:
        print("\n Aucun cas où le fuzzy-matching masque un résultat d'alias sans rapport.")

    if mismatches:
        print(f"\n  {len(mismatches)} requête(s) où le résultat final NE CONTIENT PAS "
              f"la cible attendue par la table d'alias :")
        for q, expected, got in mismatches:
            print(f"  - {q!r} : attendu {expected}, obtenu {got}")
    else:
        print("\n Toutes les requêtes avec alias connu résolvent vers la bonne cible en sortie finale.")

    print()


if __name__ == "__main__":
    main()
