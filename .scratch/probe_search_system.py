import logging, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s",
                    filename=str(Path(__file__).with_suffix(".log")))
from code_intelligence.graph.loader import get_code_intelligence_graph
G = get_code_intelligence_graph(translation_languages=["fr"], request_language="fr")
from code_intelligence.agent.tool_helpers import set_graph_ref
set_graph_ref(G)
import code_intelligence.agent.source_tools as st
def timed(label, fn):
    t = time.perf_counter()
    try:
        r = fn()
        print(label, round(time.perf_counter() - t, 1), "s OK", flush=True)
        return r
    except Exception as e:
        print(label, round(time.perf_counter() - t, 1), "s", type(e).__name__, str(e)[:120], flush=True)
for i in (1, 2):
    timed(f"objects#{i}", lambda: st.find_instance_candidates(G, "sales", model="", limit=10))
    timed(f"source#{i}", lambda: st.search_source_fragments(G, st._allowed_source_roots(), "sales", model="", limit=10, limits=st._search_limits()))
