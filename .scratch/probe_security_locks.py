import sys
from code_intelligence.graph.loader import get_code_intelligence_graph
from code_intelligence.agent.tools.analysis import analyze_security_locks
from code_intelligence.agent.tools.helpers import find_model_source_filepaths
from code_intelligence.agent.tools.analysis import _sort_filepaths_custom_first

graph = get_code_intelligence_graph()
model = sys.argv[1]
paths = _sort_filepaths_custom_first(find_model_source_filepaths(graph, model))
print("FILES (order):")
for p in paths:
    print(" ", p)
from code_intelligence.agent.tools.helpers import tool_context
question = sys.argv[3] if len(sys.argv) > 3 else ""
with tool_context(graph, None, question):
    text = analyze_security_locks.invoke({"model_name": model})
print("LEN", len(text))
needle = sys.argv[2] if len(sys.argv) > 2 else "custom_"
for i, line in enumerate(text.split("\n")):
    if needle in line:
        print(i, line[:230])
