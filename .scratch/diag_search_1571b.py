import sys, json
sys.path.insert(0, '.')
from pathlib import Path
from code_intelligence.graph.version import deserialize_graph_with_metadata
from code_intelligence.agent.resolution.matching import _fuzzy_match_graph, _business_tokens
G, _ = deserialize_graph_with_metadata(json.loads(Path('active_graph.json').read_text(encoding='utf-8')))
for q in ("bon de commande", "bon commande", "commande d'achat", "commande achat"):
    print('\nQ:', q, '| tokens:', _business_tokens(q))
    rows = _fuzzy_match_graph(q, G, threshold=60, limit=40)
    names = [m for m, s in rows]
    print('  total retenus:', len(rows), '| a 100:', sum(1 for m, s in rows if s >= 100))
    for t in ('purchase.order', 'sale.order'):
        print(f"  rang {t}:", (names.index(t) + 1) if t in names else 'absent', '| score', dict(rows).get(t))
