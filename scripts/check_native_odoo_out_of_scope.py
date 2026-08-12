#!/usr/bin/env python3
"""
scripts/check_native_odoo_out_of_scope.py

Ad hoc test, 2026-08-11: does the live agent correctly say "not in my
indexed corpus" when asked about a genuinely native Odoo model that no
custom_* module touches (directly or transitively), or does it silently
fall back to the LLM's own general pretrained knowledge of Odoo -- which
would be ungrounded, unverified against this actual instance's code, and
outside the whole point of this system (answer from the real code, not
from memory)?

`sale` was picked after checking every custom_* module's __manifest__.py
depends list: account, hr, hr_expense, hr_holidays, base, base_automation,
and purchase (transitively, via custom_asset_loan -> custom_purchase_request
-> purchase) are all touched -- sale is not, by any custom_* module, direct
or transitive.
"""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "miro-rag"))

from rag.graph import code_intelligence_agent, get_code_intelligence_graph
from code_intelligence.ci_agent_tools import ALL_CI_TOOLS, set_graph_ref

QUESTION = (
    "Qui peut confirmer un devis (sale.order) en bon de commande dans Odoo, "
    "sans aucune personnalisation -- juste le comportement standard ?"
)

# Signals the answer is honestly declining / flagging out-of-scope, in
# either phrasing the codebase already uses elsewhere (fidelity checker,
# dynamic-uncertainty guardrail) or a plain-language equivalent.
HONEST_DECLINE_MARKERS = [
    "absent du corpus",
    "not found in the indexed knowledge graph",
    "pas indexé",
    "n'est pas dans",
    "hors de mon périmètre",
    "ne peux pas classifier avec certitude",
    "aucune information",
]


def main():
    print("=" * 80)
    print(" native-odoo-out-of-scope check (sale.order)")
    print("=" * 80)
    print(f"Question: {QUESTION}\n")

    G = get_code_intelligence_graph()
    set_graph_ref(G)

    # Ground-truth check: confirm sale.order really isn't in the graph
    # before interpreting the agent's answer.
    in_graph = G.has_node("model:sale.order")
    print(f"[INFO] 'model:sale.order' present in the live graph: {in_graph}")
    print("-" * 80)

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

    declined = any(marker.lower() in answer.lower() for marker in HONEST_DECLINE_MARKERS)

    if declined:
        print("[RESULT] Agent appears to have honestly declined / flagged out-of-scope.")
    else:
        print(
            "[RESULT] Agent did NOT use any expected decline phrasing -- read the answer "
            "above carefully: did it answer from ungrounded general Odoo knowledge instead "
            "of admitting sale.order isn't in its indexed corpus?"
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
