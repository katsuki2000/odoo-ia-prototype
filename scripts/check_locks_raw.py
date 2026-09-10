#!/usr/bin/env python3
"""
scripts/check_locks_raw.py

Diagnostic-only, added 2026-08-06: isolate analyser_verrous_securite's raw
tool output (deterministic, no LLM) for custom.deep.document, to check
whether both exception messages (50k UserError, 100k ValidationError) are
present in the OBSERVATION itself before blaming the synthesis LLM for
dropping one of them.
"""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.graph.graph import get_code_intelligence_graph
from code_intelligence.agent.ci_agent_node.tools import ALL_CI_TOOLS
from code_intelligence.agent.ci_agent_node.context.tool_helpers import set_graph_ref

G = get_code_intelligence_graph()
set_graph_ref(G)

tool_map = {t.name: t for t in ALL_CI_TOOLS}
lock_tool = tool_map["analyze_security_locks"]
result = lock_tool.invoke({"model_name": "custom.deep.document"})
print("=" * 80)
print("RAW analyze_security_locks OUTPUT for custom.deep.document:")
print("=" * 80)
print(result)
print("=" * 80)
print(f"Length: {len(result)} chars")
print(f"Contains '50 000' or '50000': {'50 000' in result or '50000' in result}")
print(f"Contains '100 000' or '100000': {'100 000' in result or '100000' in result}")
print(f"Contains 'responsable comptabilité': {'responsable comptabilité' in result}")
print(f"Contains 'administrateur système': {'administrateur système' in result}")
