#!/usr/bin/env python3
"""
scripts/check_sale_order_raw_access.py

Diagnostic-only, 2026-08-12: isolate what qui_a_acces_a / evaluer_regles_
enregistrement actually return for sale.order (write access), independent
of the LLM synthesis, to check whether the agent's "aucune regle ne
s'applique" answer for check_native_odoo_out_of_scope.py's question is a
real omission (real ACL data existed and got dropped) or an accurate
reflection of what's actually in the graph (no restrictive rule at all).
"""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.graph.graph import get_code_intelligence_graph
from code_intelligence.agent.tools import ALL_CI_TOOLS
from code_intelligence.agent.tools.helpers import set_graph_ref

G = get_code_intelligence_graph()
set_graph_ref(G)

tool_map = {t.name: t for t in ALL_CI_TOOLS}

print("=" * 80)
print("qui_a_acces_a(sale.order, write) RAW OUTPUT:")
print("=" * 80)
acces_tool = tool_map.get("qui_a_acces_a")
if acces_tool is not None:
    print(acces_tool.invoke({"model_name": "sale.order", "droit": "write"}))
else:
    print("[qui_a_acces_a not found in ALL_CI_TOOLS]")

print("\n" + "=" * 80)
print("analyser_verrous_securite(sale.order) RAW OUTPUT:")
print("=" * 80)
locks_tool = tool_map.get("analyser_verrous_securite")
if locks_tool is not None:
    print(locks_tool.invoke({"model_name": "sale.order"}))
