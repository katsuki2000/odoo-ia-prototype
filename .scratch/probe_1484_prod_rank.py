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
byid = {i['id']: i['business_question'] for i in items}
cases = [("CNA-Q1","account.move"),("CNA-Q3","account.move"),("HRL-Q1","hr.leave"),("HRL-Q2","hr.leave"),("STK-Q1","stock.quant"),("MNT-Q4","maintenance.equipment"),("DDI-Q3","custom.deep.document"),("DDI-Q2","custom.deep.document"),
         ("PUR-Q1","purchase.order"),("CNA-Q2","account.move"),("SAL-Q2","sale.order"),("MNT-Q1","maintenance.equipment"),("ACC-Q5","account.move")]
inside = 0
for qid, exp in cases:
    ranked = rank_semantic_model_candidates(byid[qid], G, provider, limit=600, cache_dir=settings.SEMANTIC_INDEX_CACHE_DIR, language="fr")
    r = ranked.index(exp) + 1 if exp in ranked else None
    print(qid, exp, 'rang', r, flush=True)
