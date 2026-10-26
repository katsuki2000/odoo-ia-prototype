import sys
sys.path.insert(0, '.')
from pathlib import Path
import json
from code_intelligence.graph.version import deserialize_graph_with_metadata
from code_intelligence.agent.tools.instance_search import find_instance_candidates
G, _meta = deserialize_graph_with_metadata(json.loads(Path('active_graph.json').read_text(encoding='utf-8')))
print('langues:', list(G.graph.get('translation_languages', ())))
for m in ('model:purchase.order', 'model:purchase.requisition', 'model:purchase.request'):
    if G.has_node(m):
        a = G.nodes[m]
        print(m, 'labels=', [i.get('label') for i in a.get('business_labels', []) if isinstance(i, dict)][:6], '| desc=', str(a.get('description',''))[:60])
    else:
        print(m, 'ABSENT')
for q in ("demande achat", "demande d'achat", "purchase.request", "commande d'achat", "bon de commande", "demande de prix", "purchase order", "achat"):
    r = find_instance_candidates(G, q, limit=5)
    print('\nQ:', q, '| semantic:', r['semantic_status'])
    for c in r['candidates']:
        print(f"  {c['score']:6.1f}  {c['model']:28s} {c['labels'][:2]}")

