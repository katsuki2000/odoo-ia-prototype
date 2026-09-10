#!/usr/bin/env python3
"""
scripts/check_q6_2_lock_pollution_regression.py

Ad hoc regression check, 2026-08-10: after dropping _question_is_approval_related
as a gate on analyser_verrous_securite's forced dispatch (module 5 fix, structural
guard via find_security_lock_source_files instead), re-verify the ORIGINAL Q6.2
scenario that motivated adding the keyword gate in the first place (2026-08-06):
a pure ir.rule VISIBILITY question on account.move -- a model that DOES have a
Python lock (custom_credit_note_approval's 5000e/manager UserError) -- must NOT
have that lock's threshold wrongly cross-attributed to the ir.rule visibility
answer. The lock tool firing is now expected/fine; what must NOT happen is the
synthesis conflating the two mechanisms.

Not a claim of full coverage -- just the one concrete regression the removed
keyword gate was explicitly added to prevent, run once directly.
"""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.graph.graph import code_intelligence_agent, get_code_intelligence_graph
from code_intelligence.agent.ci_agent_node.context.agent_tools import ALL_CI_TOOLS, set_graph_ref

QUESTION = (
    "Un utilisateur qui n'appartient à AUCUN des deux groupes (ni régional, "
    "ni national) peut-il voir ce même avoir de 80 000€ ?"
)

# What must appear: the ir.rule-based visibility answer (this model has no
# group -> no group-based rule applies -> global rules only, no restriction).
EXPECTED_MARKERS = [
    "ir.rule",
]

# What must NOT appear: the 5000€ approval threshold from the UNRELATED
# Python lock, wrongly presented as if it were the answer to a VISIBILITY
# question (the exact Q6.2 regression from 2026-08-06).
FORBIDDEN_CROSS_ATTRIBUTION_MARKERS = [
    "5000",
    "5 000",
]


def main():
    print("=" * 80)
    print(" q6.2-lock-pollution-regression")
    print("=" * 80)
    print(f"Question: {QUESTION}\n")

    G = get_code_intelligence_graph()
    set_graph_ref(G)

    state = {"question": QUESTION, "chat_history": []}
    result = code_intelligence_agent(state)
    response = result.get("response")
    if response is None:
        print("[FAIL] No response object returned.")
        sys.exit(1)

    answer = response.answer
    timing = result.get("timing", {})
    print(f"Answer (hops={timing.get('ci_hop_count', '?')}):\n{answer}\n")
    print("-" * 80)

    ok = True

    for marker in EXPECTED_MARKERS:
        present = marker.lower() in answer.lower()
        print(f"[{'OK ' if present else 'MISSING'}] expected marker: {marker}")
        if not present:
            ok = False

    for marker in FORBIDDEN_CROSS_ATTRIBUTION_MARKERS:
        present = marker in answer
        if present:
            print(f"[FAIL -- CROSS-ATTRIBUTION] forbidden marker present: {marker}")
            ok = False
        else:
            print(f"[OK ] forbidden marker absent: {marker}")

    print()
    if ok:
        print("[Q6.2 REGRESSION CHECK] OK -- no cross-attribution detected.")
        sys.exit(0)
    else:
        print("[Q6.2 REGRESSION CHECK] REGRESSION FOUND -- see FAIL/MISSING lines above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
