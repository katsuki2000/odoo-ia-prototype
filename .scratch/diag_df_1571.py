import sys, json
from collections import Counter
sys.path.insert(0, '.')
from pathlib import Path
from code_intelligence.graph.version import deserialize_graph_with_metadata
from code_intelligence.agent.resolution.matching import _build_fuzzy_index, _business_tokens
G, _ = deserialize_graph_with_metadata(json.loads(Path('active_graph.json').read_text(encoding='utf-8')))
index = _build_fuzzy_index(G)
n = len(index)
df = Counter(t for label, _m in index for t in set(_business_tokens(label)))
print('entrees index:', n)
for t in ('de','du','la','le','des','et','of','the','and','to','for','par','achat','commande','bon','order','ordre','type','line','ligne','fournisseur','demande','prix','compte','date','stock'):
    print(f"{t:12s} df={df[t]:6d}  ratio={df[t]/n:.4f}")
print('top 25:', [(t, round(c/n,3)) for t, c in df.most_common(25)])
