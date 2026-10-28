"""Section 1628: build_graph() without the removed HYBRID / CODE_INTELLIGENCE routes."""
def edit(path, pairs):
    s = open(path, encoding="utf-8").read()
    for old, new in pairs:
        assert s.count(old) == 1, (path, old[:60], s.count(old))
        s = s.replace(old, new)
    open(path, "w", encoding="utf-8").write(s)


edit("core/graph/graph.py", [
    ("    workflow.add_node('hybrid_node', hybrid_node)\n", ""),
    ("        QueryRoute.HYBRID.value: 'hybrid_node',\n        QueryRoute.CODE_INTELLIGENCE.value: 'orm_agent_loop',\n", ""),
    ("    workflow.add_edge('hybrid_node', 'verify_answer')\n", ""),
])
edit("tests/test_t3_verify_node.py", [
    ('== {"generate", "hybrid_node", "orm_agent_loop"}', '== {"generate", "orm_agent_loop"}'),
])
print("ok")
