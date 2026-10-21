import json, sys
sys.path.insert(0, '.')
from code_intelligence.graph.loader import get_code_intelligence_graph
from code_intelligence.agent.semantic_retrieval import rank_semantic_model_candidates, build_semantic_embedding_function
from config import settings
G = get_code_intelligence_graph(translation_languages=["fr"], request_language="fr")
provider = build_semantic_embedding_function()
items = []
for f in ('tests/native_n1_question_bank.json', 'tests/custom_b9_question_bank.json'):
    d = json.load(open(f, encoding='utf-8')); items += d['questions'] if 'questions' in d else d['items']
hits = {1: 0, 3: 0, 5: 0, 10: 0, 20: 0}; n = 0; rows = []
for it in items:
    exp = it.get('expected_models') or []
    if not exp: continue
    ranked = rank_semantic_model_candidates(it['business_question'], G, provider, limit=600, cache_dir=settings.SEMANTIC_INDEX_CACHE_DIR, language="fr")
    best = min((ranked.index(m) + 1 for m in exp if m in ranked), default=None)
    n += 1
    for k in hits: hits[k] += bool(best and best <= k)
    rows.append((it['id'], best))
print('questions notees:', n)
print({f'top{k}': v for k, v in hits.items()})
print('hors top 10:', [(i, b) for i, b in rows if not b or b > 10])
