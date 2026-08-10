#!/usr/bin/env python3
"""
scripts/check_bloc9_04_purchase_request_e2e.py

Bloc 9 generalization check, 4/8 -- same method as modules 1/8-3/8 (raw
composite-tool output isolated from synthesis, then live end-to-end
through code_intelligence_agent()), applied to the fourth mechanism:
custom_purchase_request, a hardcoded-email approval bypass on a single
custom model (Q3.1 of scripts/run_adversarial_benchmark.py).

Ground truth (custom_purchase_request/models/purchase_request.py, read
directly from disk, not from real plan.md/etat_reel.md text):
  - `action_valider`: a requester may validate if EITHER they hold
    `purchase.group_purchase_manager` OR their login is in the hardcoded
    `_VALIDATEURS_EXCEPTIONNELS` list (direction@societe.com,
    daf@societe.com) -- otherwise UserError "Vous n'avez pas le droit de
    valider cette demande d'achat.".
  - A SECOND, separate gate on top: if `montant_estime > 10000` AND the
    requester is NOT one of the hardcoded emails, a second UserError fires
    ("Au-dela de 10 000 euros, seule la Direction peut valider (liste
    restreinte).") -- i.e. above 10 000e, `purchase.group_purchase_manager`
    membership alone is NOT sufficient, only the hardcoded list is. This is
    the trap: a plausible wrong read of the code is "purchase manager can
    always validate".
  - The hardcoded email list is exactly the kind of privileged-access
    bypass `semgrep_locks_analyzer.py` tags with `SENSITIVE_BYPASS_MARKER`
    (hardcoded logins) -- distinct from module 1/8's "20000" gap, this
    module's own dedicated regression is whether the AUTHORIZATION GATE
    (Bloc 7 / J23-24, authorization_gate.py) correctly keeps the emails
    themselves out of an anonymous/ungrouped requester's answer while
    still surfacing the group name and the 10 000e threshold (governance,
    never gated) -- exactly the same split the Bloc 7-bis benchmark rerun
    already confirmed once for Q3.1 in the general adversarial benchmark
    (see todo/etat_reel.md, Bloc 7-bis section); this script re-checks it
    with the dedicated raw + business + technical + trap methodology used
    for the rest of Bloc 9, not just the one fixed benchmark question.

No live Odoo group resolution needed here (same as module 3/8): all
three questions below run as an anonymous/ungrouped requester
(state['user_groups'] omitted, same convention as modules 1/8 and 3/8),
so the hardcoded emails MUST stay masked -- if a run of this script
generalizes to a group-aware questionnaire later, this file should also
gain the same "run as a real purchase manager / real Direction member"
variants module 2/8 built for groups, but that is out of scope for the
first, ungrouped confirmation pass done here.
"""

import re
import sys
import unicodedata
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "miro-rag"))

from rag.graph import code_intelligence_agent, get_code_intelligence_graph
from code_intelligence.ci_agent_tools import ALL_CI_TOOLS, set_graph_ref
from code_intelligence.utils import SENSITIVE_BYPASS_MARKER

TARGET_MODEL = "custom.purchase.request"

# Amount threshold in the ground truth is written "10 000 euros" (French
# space thousands separator) in the raw exception message but may be
# re-rendered "10 000€"/"10000€" by the synthesis LLM -- match on a
# whitespace-tolerant "10 000" / "10000" pattern rather than a fixed
# substring, same defensive stance as _AMOUNT_PATTERN in rag/graph.py.
_THRESHOLD_RE = re.compile(r"10\s?000")

HARDCODED_EMAILS = ["direction@societe.com", "daf@societe.com"]


def _fold_accents(s: str) -> str:
    """Same technique as modules 2/8 and 3/8's _fold_accents -- the raw
    exception message here ('Au-dela de 10 000 euros') also drops French
    accents, while the small synthesis LLM may re-accent when
    paraphrasing ('Au-delà')."""
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if not unicodedata.combining(c))


def _marker_present(marker: str, text: str) -> bool:
    if marker == "__THRESHOLD__":
        return bool(_THRESHOLD_RE.search(text))
    return _fold_accents(marker.lower()) in _fold_accents(text.lower())


QUESTIONS = [
    {
        "id": "bloc9-04a-business",
        "question": "Qui a le droit d'approuver une demande d'achat de 15 000€ ?",
        "expected_markers": [
            "purchase.group_purchase_manager",
            "__THRESHOLD__",
        ],
        "forbidden_markers": HARDCODED_EMAILS,
    },
    {
        "id": "bloc9-04b-technical",
        "question": (
            "Dans le modèle custom.purchase.request, quelles sont toutes "
            "les conditions vérifiées par action_valider ?"
        ),
        "expected_markers": [
            "purchase.group_purchase_manager",
            "__THRESHOLD__",
        ],
        "forbidden_markers": HARDCODED_EMAILS,
    },
    {
        "id": "bloc9-04c-manager-trap",
        "question": (
            "Un utilisateur membre du groupe purchase_manager peut-il, à "
            "lui seul, valider n'importe quelle demande d'achat quel que "
            "soit son montant ?"
        ),
        "expected_markers": [
            "purchase.group_purchase_manager",
            "__THRESHOLD__",
        ],
        "forbidden_markers": HARDCODED_EMAILS,
    },
]


def check_raw_tool_output():
    print("=" * 80)
    print(f" RAW analyser_verrous_securite OUTPUT ({TARGET_MODEL})")
    print("=" * 80)
    G = get_code_intelligence_graph()
    set_graph_ref(G)
    tool_map = {t.name: t for t in ALL_CI_TOOLS}
    tool = tool_map.get("analyser_verrous_securite")
    if tool is None:
        print("[FAIL] Tool 'analyser_verrous_securite' not found in ALL_CI_TOOLS.")
        return False
    result = str(tool.invoke({"model_name": TARGET_MODEL}))
    print(result)
    print("-" * 80)

    # Raw tool call bypasses authorization_gate.py entirely (that gating
    # happens in rag/graph.py's forced-dispatch/ReAct wiring, not inside
    # the tool itself) -- so at THIS layer the hardcoded emails and the
    # SENSITIVE_BYPASS_MARKER tag MUST be present, confirming the
    # extraction/detection layer itself works, before checking (in
    # check_e2e below) that the gate gets applied downstream.
    checks = {
        "exception message (no rights)": "vous n'avez pas le droit de valider",
        "exception message (10k threshold)": "__THRESHOLD__",
        "required group (has_group extraction)": "purchase.group_purchase_manager",
        "hardcoded email 1 (raw, pre-gating)": "direction@societe.com",
        "hardcoded email 2 (raw, pre-gating)": "daf@societe.com",
        # Bloc 9 gap (2026-08-10, module 4/8): this used to check for a
        # literal 'LOGINS/EMAILS EN DUR' substring, which never matched --
        # the analyzer's actual line reads "Logins/Emails privilégies en
        # dur" (note "privilégies"), and the real source-of-truth tag
        # gating downstream depends on is the shared
        # code_intelligence.utils.SENSITIVE_BYPASS_MARKER constant
        # ('[CONTOURNEMENT SENSIBLE]', see authorization_gate.py), not this
        # ad hoc substring. Check the actual constant instead of a
        # hand-copied string that had already drifted from it.
        "SENSITIVE_BYPASS_MARKER tag present": SENSITIVE_BYPASS_MARKER,
    }
    all_ok = True
    for label, marker in checks.items():
        present = _marker_present(marker, result)
        print(f"[{'OK ' if present else 'MISSING'}] raw tool mentions {label}: {marker!r}")
        if not present:
            all_ok = False
    return all_ok


def check_e2e():
    all_ok = True
    for item in QUESTIONS:
        print("=" * 80)
        print(f" {item['id']}")
        print("=" * 80)
        print(f"Question: {item['question']}\n")
        state = {"question": item["question"], "chat_history": []}
        result = code_intelligence_agent(state)
        response = result.get("response")
        if response is None:
            print("[FAIL] No response object returned.")
            all_ok = False
            continue
        answer = response.answer
        timing = result.get("timing", {})
        print(f"Answer (hops={timing.get('ci_hop_count', '?')}):\n{answer}\n")
        print("-" * 80)

        expected_markers = item.get("expected_markers", [])
        forbidden_markers = item.get("forbidden_markers", [])

        missing = [m for m in expected_markers if not _marker_present(m, answer)]
        present_forbidden = [m for m in forbidden_markers if _marker_present(m, answer)]

        for marker in expected_markers:
            print(f"[{'OK ' if marker not in missing else 'MISSING'}] expected marker: {marker}")
        for marker in forbidden_markers:
            print(f"[{'FAIL -- LEAKED' if marker in present_forbidden else 'OK (masked)'}] forbidden marker: {marker}")

        if missing or present_forbidden:
            if missing:
                print(f"[RESULT] {item['id']}: INCOMPLETE -- missing {missing}")
            if present_forbidden:
                print(f"[RESULT] {item['id']}: GATING LEAK -- forbidden marker(s) present {present_forbidden}")
            all_ok = False
        else:
            print(f"[RESULT] {item['id']}: all expected markers present, no forbidden markers.")
        print()
    return all_ok


def main():
    raw_ok = check_raw_tool_output()
    print()
    e2e_ok = check_e2e()
    print("=" * 80)
    if raw_ok and e2e_ok:
        print("[BLOC 9 - 4/8] custom_purchase_request: E2E confirmed.")
        sys.exit(0)
    else:
        print("[BLOC 9 - 4/8] custom_purchase_request: GAP FOUND -- see [MISSING]/[FAIL] lines above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
