"""Transitions presentes dans l'ancien graphe et absentes du nouveau (jetable, section 1525).

Usage : python3 .scratch/diff_workflow_edges_1525.py ANCIEN.json NOUVEAU.json
"""
import json
import sys


def transitions(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    graph = data.get("graph", data)
    nodes = {node["id"]: node for node in graph["nodes"]}
    found = set()
    for edge in graph.get("links", graph.get("edges", [])):
        if edge.get("edge_type") != "TRANSITIONS_VIA":
            continue
        source, target = nodes.get(edge["source"], {}), nodes.get(edge["target"], {})
        records = edge.get("button_transitions") or [{"method_name": edge.get("method_name", "")}]
        for record in records:
            found.add((source.get("model", ""), record.get("method_name", ""), source.get("state_value", ""), target.get("state_value", "")))
    return found


old, new = transitions(sys.argv[1]), transitions(sys.argv[2])
removed, added = sorted(old - new), sorted(new - old)
print(f"transitions : avant={len(old)} apres={len(new)} retirees={len(removed)} ajoutees={len(added)}")
for label, rows in (("RETIREES", removed), ("AJOUTEES", added)):
    print(f"\n{label}")
    for model, method, origin, target in rows:
        print(f"  {model}.{method}: {origin} -> {target}")
