import sys, json, time
sys.path.insert(0, '.')
from code_intelligence.graph import get_code_intelligence_graph
from code_intelligence.agent.tools.source_search import search_source_fragments, SearchLimits
from code_intelligence.agent.tools.source import _allowed_source_roots
G = get_code_intelligence_graph(); roots = _allowed_source_roots()
for q, m in (('button_confirm approval_allowed', 'purchase.order'), ('Sales Order unlock button', 'sale.order')):
    t = time.time(); r = search_source_fragments(G, roots, q, model=m, limit=8, limits=SearchLimits(), candidate_models=[m])
    print(round(time.time() - t, 2), 's', r['coverage']['files_indexed'], 'files')
