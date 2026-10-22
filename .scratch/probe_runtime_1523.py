"""Sonde jetable (1523) : sortie complete, sans LLM, des outils deterministes vus par l'agent."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from code_intelligence.agent.tool_helpers import set_graph_ref
from code_intelligence.evaluation.e1.run import load_graph
from code_intelligence.agent.tools.structure import describe_workflow
from code_intelligence.agent.tools.analysis import analyze_security_locks

set_graph_ref(load_graph())
for name, tool_, arg in [("describe_workflow", describe_workflow, "hr.leave"),
                         ("analyze_security_locks", analyze_security_locks, "hr.leave"),
                         ("describe_workflow", describe_workflow, "sale.order")]:
    print(f"\n######## {name}({arg}) ########")
    print(tool_.invoke({"model_name": arg}))
