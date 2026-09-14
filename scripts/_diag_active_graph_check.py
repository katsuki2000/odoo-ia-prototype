import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code_intelligence.graph.loader import get_code_intelligence_graph
from code_intelligence.agent.resolver import resolve_business_term

G = get_code_intelligence_graph()

print(f"Total nodes: {G.number_of_nodes()}")

model_nodes = [(n, d) for n, d in G.nodes(data=True) if d.get("node_type") == "Model"]
print(f"Total Model nodes: {len(model_nodes)}")

deep_matches = [(n, d.get("name")) for n, d in model_nodes if "deep" in str(d.get("name", "")).lower()]
print(f"Model nodes containing 'deep': {deep_matches}")

has_exact = G.has_node("model:custom.deep.document")
print(f"G.has_node('model:custom.deep.document'): {has_exact}")

custom_models = sorted(d.get("name") for _n, d in model_nodes if str(d.get("name", "")).startswith("custom."))
print(f"All 'custom.*' Model nodes ({len(custom_models)}): {custom_models}")

q = "Quel est le lien entre base et custom.deep.document ?"
r = resolve_business_term(q, G)
print(f"\nresolve_business_term({q!r}):")
print(f"  -> models={r.resolved_models}  source={r.source_step}  resolu={r.is_resolved}")
