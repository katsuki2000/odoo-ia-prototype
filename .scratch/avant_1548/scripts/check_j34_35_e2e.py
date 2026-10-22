#!/usr/bin/env python3
"""
scripts/check_j34_35_e2e.py

/J34-35 integration sanity check, added 2026-08-06.

test_j34_35_deep_custom_modules.py exercises the extraction/parsing layer
(manifest_parser, python_extractor, xml_extractor, semgrep_locks_analyzer,
graph_builder) directly and in isolation against custom_deep_inheritance_
security -- it never calls code_intelligence_agent() end-to-end the way
test_j25_26_e2e_purchase_bypass_gate.py does for . Unlike yesterday's
gap (a brand-new tool needing an explicit dispatch wire), no plumbing is
expected to be missing here -- the module sits under /home/user/odoo-17.0/
addons/ like any other custom module, so the production graph builder picks
it up automatically. This script is a one-shot live confirmation that the
whole pipeline (business/technical resolution, graph traversal across 5
levels of _inherit, security lock extraction, synthesis) actually produces
a correct answer end-to-end, not just correct unit-level pieces.

Ground truth (models/deep_document.py):
  - CustomLevel2Document.action_validate_level2(): amount > 50000 requires
    account.group_account_manager, else UserError "Seul un responsable
    comptabilité peut valider au-delà de 50 000€."
  - CustomLevel5Document.action_final_approve(): amount > 100000 requires
    base.group_system, else ValidationError "Approbation finale > 100k€
    réservée à l'administrateur système."

Uses the technical model name directly in the question (rather than a
business term) to isolate graph/synthesis correctness from business
term resolution, which is a separate concern.
"""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.graph.graph import code_intelligence_agent

QUESTION = (
    "Dans le modèle custom.deep.document, qui a le droit de valider un "
    "enregistrement de plus de 50 000€, et y a-t-il une restriction "
    "supplémentaire au-delà de 100 000€ ?"
)

EXPECTED_MARKERS = [
    "account.group_account_manager",
    "base.group_system",
]


def main():
    print("=" * 80)
    print(" J34-35 — LIVE END-TO-END CHECK (custom.deep.document)")
    print("=" * 80)
    print(f"Question: {QUESTION}\n")

    state = {"question": QUESTION, "chat_history": []}
    result = code_intelligence_agent(state)
    response = result.get("response")

    if response is None:
        print("[FAIL] No response object returned.")
        sys.exit(1)

    answer = response.answer
    timing = result.get("timing", {})
    print(f"Answer (hops={timing.get('ci_hop_count', '?')}, "
          f"effective={timing.get('ci_effective_time', '?')}s):\n")
    print(answer)
    print("\n" + "-" * 80)

    for marker in EXPECTED_MARKERS:
        found = marker in answer
        status = "OK " if found else "MISSING"
        print(f"[{status}] expected marker: {marker}")

    missing = [m for m in EXPECTED_MARKERS if m not in answer]
    if missing:
        print(f"\n[RESULT] INCOMPLETE -- missing: {missing}")
        sys.exit(1)
    print("\n[RESULT] All expected markers present -- pipeline confirmed end-to-end.")


if __name__ == "__main__":
    main()
