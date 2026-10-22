"""Section 945: cross-domain model extension ordering and active tool inventory."""

import json
from pathlib import Path
import networkx as nx

from code_intelligence.rules.structure import (
    inspect_module_cross_domain_extensions,
)


def test_inspect_module_cross_domain_extensions_prioritizes_business_models():
    G = nx.DiGraph()
    G.add_node("module:sale", node_type="Module")
    G.add_node("model:sale.order", node_type="Model", filepaths=[])
    G.add_edge("model:sale.order", "module:sale", edge_type="DEFINED_IN", role="declares")

    # res.company has high degree (e.g. 200)
    G.add_node("model:res.company", node_type="Model", filepaths=[])
    G.add_edge("model:res.company", "module:sale", edge_type="DEFINED_IN", role="extends")
    for i in range(200):
        dummy = f"model:dummy_{i}"
        G.add_node(dummy, node_type="Model")
        G.add_edge(dummy, "model:res.company", edge_type="RELATION")

    # account.move has lower degree (e.g. 50)
    G.add_node("model:account.move", node_type="Model", filepaths=[])
    G.add_edge("model:account.move", "module:sale", edge_type="DEFINED_IN", role="extends")
    for i in range(50):
        dummy = f"model:dummy_acc_{i}"
        G.add_node(dummy, node_type="Model")
        G.add_edge(dummy, "model:account.move", edge_type="RELATION")

    exts = inspect_module_cross_domain_extensions(G, "sale")
    assert len(exts) == 2
    # account.move (business model) must come before res.company (base registry)
    assert exts[0].model_name == "account.move"
    assert exts[1].model_name == "res.company"


def test_native_n1_question_bank_sal_q3_expected_tools():
    qbank_path = Path(__file__).resolve().parents[2] / "tests" / "native_n1_question_bank.json"
    with open(qbank_path, encoding="utf-8") as f:
        data = json.load(f)
    questions = data.get("questions", data)
    sal_q3 = next((q for q in questions if q.get("id") == "SAL-Q3"), None)
    assert sal_q3 is not None
    assert "analyze_method_override_chain" not in sal_q3.get("expected_tools", [])
    assert "trace_full_inheritance" in sal_q3.get("expected_tools", [])
    assert "list_involved_modules" in sal_q3.get("expected_tools", [])
