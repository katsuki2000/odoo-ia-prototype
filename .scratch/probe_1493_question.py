import sys
sys.path.insert(0, '.')
from code_intelligence.graph.loader import get_code_intelligence_graph
from code_intelligence.agent.resolution import fuzzy_lookup
from code_intelligence.agent.resolution.arbitration import ArbitrationTrace, _llm_arbitrate as real
from code_intelligence.agent.resolver import resolve_business_term
from core.llm.llm_client import get_chat_llm
G = get_code_intelligence_graph()
use_llm = len(sys.argv) > 1
llm = get_chat_llm(temperature=0.0, max_retries=0, max_tokens=1024, model_kwargs={"parallel_tool_calls": False}) if use_llm else object()
seen = {}
def spy(q, cands, l, ctx=None):
    seen.update(cands=list(cands), ctx=ctx or {})
    return real(q, cands, l, ctx) if use_llm else ArbitrationTrace(None, 'none', '[]')
fuzzy_lookup._llm_arbitrate = spy
for label, q in (("droite", "qui s'occupe d'approuver les demandes de mise à disposition ?"), ("courbe", "qui s’occupe d’approuver les demandes de mise à disposition ?")):
    seen.clear()
    r = resolve_business_term(q, G, llm=llm, language='fr')
    print(label, '->', r.source_step, r.resolved_models, '| arbitrage:', getattr(r, 'arbitration', None) or '', flush=True)
    print('   liste:', [(i+1, m) for i, m in enumerate(seen.get('cands', [])[:12])], flush=True)
