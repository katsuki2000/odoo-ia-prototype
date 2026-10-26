import sys, json
sys.path.insert(0, '.')
from pathlib import Path
from rapidfuzz import fuzz
from code_intelligence.graph.version import deserialize_graph_with_metadata
from code_intelligence.agent.resolution.matching import _build_fuzzy_index, _business_text, _FUZZY_INDEX_CACHE
G, _ = deserialize_graph_with_metadata(json.loads(Path('active_graph.json').read_text(encoding='utf-8')))
index = _build_fuzzy_index(G)
types = _FUZZY_INDEX_CACHE[G]['fuzzy_entry_types']
q = _business_text('bon de commande')
seen = {}
for (label, model), t in zip(index, types):
    s = fuzz.token_set_ratio(q, _business_text(label))
    if s >= 100 and model in ('res.company','product.product','account.tax','account.move.line','purchase.order.line','purchase.order'):
        seen.setdefault(model, []).append((t, label[:60], s))
for m, rows in seen.items():
    print(m, rows[:3])
