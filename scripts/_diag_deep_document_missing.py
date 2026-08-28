import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code_intelligence.ci_graph_loader import get_code_intelligence_graph

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
