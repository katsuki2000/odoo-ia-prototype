"""Ablation of card node types for the dense index, rank of the expected model. Run from the repo root."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from code_intelligence.evaluation.e1 import systems
from code_intelligence.evaluation.e1.cases import load_calibration_cases
from code_intelligence.evaluation.e1.config import load_e1_config
from code_intelligence.evaluation.e1.dense_index import resolve_e1_embedding_function
from code_intelligence.evaluation.e1.projection import ModelProjector, project_candidates
from code_intelligence.evaluation.e1.run import load_graph

DATA = Path("code_intelligence/evaluation/e1/data")
FILES = ("calibration_cases.json", "role_calibration_cases.json", "role_calibration_cases_ext.json")
SETS = {
    "M": ("Model",), "MM": ("Model", "Menu"),
    "MM+Group": ("Model", "Menu", "Group"), "MM+Rule": ("Model", "Menu", "Rule"),
    "MM+Field": ("Model", "Menu", "Field"), "MM+Method": ("Model", "Menu", "Method"),
    "MM+Button": ("Model", "Menu", "Button"), "ALL": None,
}
cases = [c for f in FILES for c in load_calibration_cases(DATA / f)[0]]
config = load_e1_config()
function = resolve_e1_embedding_function()
if function is None:
    sys.exit("no embedding function")
all_types = list(config["card_node_types"])
ranks = {name: {} for name in SETS}
for case in cases:
    graph = load_graph([case.language])
    projector = ModelProjector(graph)
    index = systems._dense_index(graph, case.language, all_types, function, batch_size=int(config["dense_batch_size"]))
    targets = set(case.expected_objects)
    for name, types in SETS.items():
        hits = index.search(case.question, function, top_k=len(index.cards), node_types=types)
        models = project_candidates([h.object_ref for h in hits], projector)
        found = [models.index(t) + 1 for t in targets if t in models]
        ranks[name][case.case_id] = min(found) if found else None
    print(case.case_id, {n: ranks[n][case.case_id] for n in SETS}, flush=True)
def stats(r):
    v = list(r.values()); n = len(v)
    at = lambda k: sum(1 for x in v if x and x <= k)
    mrr = sum(1 / x for x in v if x) / n
    return f"r@1={at(1)} r@5={at(5)} r@10={at(10)} r@20={at(20)} n={n} MRR={mrr:.3f}"
print("=== RESULTATS ===")
for name in SETS:
    print(f"{name:<10} {stats(ranks[name])}")
json.dump(ranks, open(".scratch/probe_d12_ablation.json", "w"), indent=1)
