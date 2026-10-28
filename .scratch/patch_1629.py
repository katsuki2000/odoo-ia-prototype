import re
from pathlib import Path


def edit(path, pairs):
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    for old, new in pairs:
        assert text.count(old) == 1, (path, old[:60])
        text = text.replace(old, new)
    p.write_text(text, encoding="utf-8")


node = Path("erp_data/orm_agent_node.py")
text = node.read_text(encoding="utf-8")
start = text.index("def hybrid_node(")
text = text[:start].rstrip("\n") + "\n"
node.write_text(text, encoding="utf-8")
edit(node, [
    ("ORM ReAct agent loop (ERP data queries) and hybrid pipeline node.", "ORM ReAct agent loop (ERP data queries)."),
    ("from document_rag.generate_node import generate\n", ""),
])

prompts = Path("erp_data/prompts.py")
text = prompts.read_text(encoding="utf-8")
start = text.index("def build_hybrid_combine_prompt(")
end = text.index("__all__ = [")
prompts.write_text(text[:start] + text[end:], encoding="utf-8")
edit(prompts, [('    "build_hybrid_combine_prompt",\n', "")])

edit("core/graph/graph.py", [
    ("from erp_data.orm_agent_node import hybrid_node, orm_agent_loop", "from erp_data.orm_agent_node import orm_agent_loop"),
])
edit("core/graph/graph_compat.py", [
    ("from erp_data.orm_agent_node import (\n    orm_agent_loop,\n    hybrid_node,\n)", "from erp_data.orm_agent_node import orm_agent_loop"),
])
edit("core/session/reasoning_trace_logger.py", [
    ('# "documentaire" | "donnees_erp" | "code_intelligence" | "hybride"', '# "documentaire" | "donnees_erp"'),
])
