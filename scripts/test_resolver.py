import sys
import json
import networkx as nx
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code_intelligence.business_resolver import resolve_business_term

print("Loading graph...")
G = nx.node_link_graph(json.loads(open('/home/user/odoo-17.0/addons/knowledge_graph/knowledge_graph.json').read()))
print(f"Graph: {G.number_of_nodes()} nodes\n")

queries = [
    'Qui peut approuver un avoir de 25000€ ?',
    'Comment fonctionne la facturation électronique ?',
    'demande de congé urgent',
    'purchase order approval',
    'mise à disposition de matériel',
]

extra_cases = [
    "avoirs",                    # bug n°1 : doit résoudre en alias, pas fuzzy res.partner
    "avoir",
    "congé",
    "congés",
    "démande de congé",          # variante avec accent parasite, doit rester robuste
    "mise à disposition",        # multi-mots, ordre préservé
    "disposition à mise",        # ordre inversé -> ne doit PAS matcher static_alias (sinon alerte faux-positif)
]

print("=== Standard Queries ===")
for q in queries:
    r = resolve_business_term(q, G)
    print(f"Q: {q!r}")
    print(f"   -> models={r.resolved_models[:3]}  conf={r.confidence}  step={r.source_step}")
    print(f"      reason={r.reason[:120]}")

print("\n=== Non-Regression Extra Cases ===")
for q in extra_cases:
    r = resolve_business_term(q, G)
    print(f"Q: {q!r:25s} -> source={r.source_step:18s}, modèles={r.resolved_models}, résolu={r.is_resolved}")
