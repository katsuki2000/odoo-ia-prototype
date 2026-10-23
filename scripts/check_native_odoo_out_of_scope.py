#!/usr/bin/env python3
"""
scripts/check_native_odoo_out_of_scope.py

Ad hoc test, 2026-08-11, RETARGETED 2026-08-13: does the live agent
correctly say "not in my indexed corpus" when asked about a genuinely
native Odoo model that no custom module touches (directly or
transitively) and that isn't loaded by any other mechanism either, or
does it silently fall back to the LLM's own general pretrained knowledge
of Odoo -- which would be ungrounded, unverified against this actual
instance's code, and outside the whole point of this system (answer from
the real code, not from memory)?

Originally targeted `sale.order`, picked after checking every custom
module's __manifest__.py depends list only. That check missed a SECOND,
independent loading path in rag/graph.py: `CORE_MODULES_ALWAYS_LOADED =
["account", "sale", "stock"]` (added 2026-08-12, replacing hand-maintained
fake_data/code stand-ins with the real Odoo source) loads `sale`
unconditionally, regardless of any custom dependency. Confirmed live
('model:sale.order' in graph: True) -- the premise was invalid, not the
agent's behavior on that question. Retargeted to `mrp` (Manufacturing):
depends only on ['product', 'stock', 'resource'] (per its own
__manifest__.py) -- none of which is itself in CORE_MODULES_ALWAYS_LOADED,
miro_ai, any custom module, or a custom module's direct dependency
(account, hr, hr_expense, hr_holidays, base, base_automation, purchase --
see every custom module's __manifest__.py depends list). Re-verify this reasoning
against both loading paths in rag/graph.py before reusing this script if
either one changes again.
"""

import sys
import unicodedata
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.graph.graph import code_intelligence_agent, get_code_intelligence_graph
from code_intelligence.agent.tools.helpers import set_graph_ref

QUESTION = (
    "Qui peut lancer un ordre de fabrication (mrp.production) dans Odoo, "
    "sans aucune personnalisation -- juste le comportement standard ?"
)

# Signals the answer is honestly declining / flagging out-of-scope, in
# either phrasing the codebase already uses elsewhere (fidelity checker,
# dynamic-uncertainty guardrail) or a plain-language equivalent.
#
# 2026-08-13 fix: none of these matched the actual (correct!) live answer
# once _force_out_of_scope_model_answer (rag/graph.py) was added -- its
# fixed template says "n'est pas present dans le corpus indexe", which
# this list's closest entry ("n'est pas dans") doesn't cover ("present"
# sits in between) and none of the accented entries cover either (that
# template is deliberately unaccented). Confirmed real script false
# negative, not a real gap: added the exact substring from that template,
# and switched matching to accent-folded (same _fold_accents technique
# already used standalone in scripts 2/8, 5/8, 6/8, 7/8 -- defined locally
# here too rather than importing from deterministic_tools, consistent with
# how those other check scripts do it, since this is a standalone CLI tool
# and not part of the application package itself).
HONEST_DECLINE_MARKERS = [
    "absent du corpus",
    "not found in the indexed knowledge graph",
    "pas indexe",
    "n'est pas dans",
    "pas present dans le corpus indexe",
    "hors de mon perimetre",
    "ne peux pas classifier avec certitude",
    "aucune information",
]


def _fold_accents(s: str) -> str:
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if not unicodedata.combining(c))


def main():
    print("=" * 80)
    print(" native-odoo-out-of-scope check (mrp.production)")
    print("=" * 80)
    print(f"Question: {QUESTION}\n")

    G = get_code_intelligence_graph()
    set_graph_ref(G)

    # Ground-truth check: confirm mrp.production really isn't in the graph
    # before interpreting the agent's answer.
    in_graph = G.has_node("model:mrp.production")
    print(f"[INFO] 'model:mrp.production' present in the live graph: {in_graph}")
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

    declined = any(
        _fold_accents(marker.lower()) in _fold_accents(answer.lower())
        for marker in HONEST_DECLINE_MARKERS
    )

    if declined:
        print("[RESULT] Agent appears to have honestly declined / flagged out-of-scope.")
    else:
        print(
            "[RESULT] Agent did NOT use any expected decline phrasing -- read the answer "
            "above carefully: did it answer from ungrounded general Odoo knowledge instead "
            "of admitting mrp.production isn't in its indexed corpus?"
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
