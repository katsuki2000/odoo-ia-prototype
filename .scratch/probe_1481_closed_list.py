import json, sys
sys.path.insert(0, '.')
from code_intelligence.graph.loader import get_code_intelligence_graph
from code_intelligence.agent.resolution import fuzzy_lookup
from code_intelligence.agent.resolution.arbitration import ArbitrationTrace
from code_intelligence.agent.resolver import resolve_business_term
G = get_code_intelligence_graph()
seen = {}
def fake(q, cands, llm, ctx=None):
    seen.update(cands=list(cands), ctx=ctx or {})
    return ArbitrationTrace(None, 'none', '[]')
fuzzy_lookup._llm_arbitrate = fake
items = []
for f in ('tests/native_n1_question_bank.json', 'tests/custom_b9_question_bank.json'):
    d = json.load(open(f, encoding='utf-8')); items += d['questions'] if 'questions' in d else d['items']
it = next(i for i in items if i['id'] == sys.argv[1])
r = resolve_business_term(it['business_question'], G, llm=object(), language='fr')
print(r.source_step, r.resolved_models)
for n, m in enumerate(seen.get('cands', []), 1):
    print(n, m, '|', seen['ctx'].get(m, '')[:90])
