import sys
sys.path.insert(0, "/media/donnee/projets/odoo-ia-prototype")

from code_intelligence.graph.loader import get_code_intelligence_graph
from code_intelligence.agent.tool_helpers import set_graph_ref, set_current_question
from code_intelligence.agent.tools.analysis import analyze_security_locks
from code_intelligence.agent.tools import ALL_CI_TOOLS

question = ("Quelles regles empechent de supprimer une commande d'achat ou une de ses lignes selon leur etat, "
            "et quelle contrainte SQL distincte s'applique sur les lignes elles-memes ?")

G = get_code_intelligence_graph()
set_graph_ref(G)
set_current_question(question)

print("=== analyze_security_locks(purchase.order) RAW ===")
out1 = analyze_security_locks.invoke({"model_name": "purchase.order"})
print(out1)
print(f"\n[len={len(out1)}]")

print("\n\n=== analyze_security_locks(purchase.order.line) RAW ===")
out2 = analyze_security_locks.invoke({"model_name": "purchase.order.line"})
print(out2)
print(f"\n[len={len(out2)}]")

data_constraints_tool = None
for t in ALL_CI_TOOLS:
    if t.name == "analyze_data_constraints":
        data_constraints_tool = t
        break

print("\n\n=== analyze_data_constraints(purchase.order.line) RAW ===")
out3 = data_constraints_tool.invoke({"model_name": "purchase.order.line"})
print(out3)
print(f"\n[len={len(out3)}]")
