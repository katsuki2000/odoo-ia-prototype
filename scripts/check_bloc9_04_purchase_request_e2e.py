#!/usr/bin/env python3
"""
scripts/check_bloc9_04_purchase_request_e2e.py

 generalization check, 4/8 -- same method as modules 1/8-3/8 (raw
composite-tool output isolated from synthesis, then live end-to-end
through code_intelligence_agent()), applied to the fourth mechanism:
custom_purchase_request, a hardcoded-email approval bypass on a single
custom model (Q3.1 of scripts/run_adversarial_benchmark.py).

Ground truth (custom_purchase_request/models/purchase_request.py, read
directly from disk, not from real / text):
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
     correctly keeps the emails
    themselves out of an anonymous/ungrouped requester's answer while
    still surfacing the group name and the 10 000e threshold (governance,
    never gated) -- exactly the same split the  benchmark rerun
    already confirmed once for Q3.1 in the general adversarial benchmark
    ; this script re-checks it
    with the dedicated raw + business + technical + trap methodology used
    for the rest of , not just the one fixed benchmark question.

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

from core.graph import code_intelligence_agent, get_code_intelligence_graph, query_graph
from code_intelligence.ci_agent_tools import ALL_CI_TOOLS, set_graph_ref
from code_intelligence.utils import SENSITIVE_BYPASS_MARKER

TARGET_MODEL = "custom.purchase.request"

# Amount threshold in the ground truth is written "10 000 euros" (French
# space thousands separator) in the raw exception message but may be
# re-rendered "10 000€"/"10000€" by the synthesis LLM -- match on a
# whitespace-tolerant "10 000" / "10000" pattern rather than a fixed
# substring, same defensive stance as _AMOUNT_PATTERN in rag/graph.py.
_THRESHOLD_RE = re.compile(r"10\s?000")

# gap (2026-08-26, section 183/186): the previous version of this
# script only ever checked for the PRESENCE of the group xmlid and the
# threshold marker, never that the answer correctly states the group is
# INSUFFICIENT above that threshold -- so it would have passed even on
# the exact wrong answer diagnosed in section 178 ("l'autorite requise
# est donc les utilisateurs appartenant au groupe
# purchase.group_purchase_manager"), which directly contradicts the
# ground truth ("Le groupe purchase_manager ne suffit pas >10000E. Seuls
# logins dans _VALIDATEURS_EXCEPTIONNELS peuvent valider"). This marker
# closes that blind spot: any ONE of these phrases signals the answer
# correctly conveys insufficiency, without requiring an exact wording
# match (the synthesis LLM paraphrases this governance point in several
# equivalent ways across runs).
_GROUP_INSUFFICIENT_RE = re.compile(
    r"(ne suffit pas|insuffisant|pas suffisant|liste restreinte|"
    r"seule la direction|ne suffisent pas)",
    re.IGNORECASE,
)

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
    if marker == "__GROUP_INSUFFICIENT__":
        return bool(_GROUP_INSUFFICIENT_RE.search(_fold_accents(text)))
    return _fold_accents(marker.lower()) in _fold_accents(text.lower())


QUESTIONS = [
    {
        "id": "",
        "question": "Qui a le droit d'approuver une demande d'achat de 15 000€ ?",
        "expected_markers": [
            "purchase.group_purchase_manager",
            "__THRESHOLD__",
            "__GROUP_INSUFFICIENT__",
        ],
        "forbidden_markers": HARDCODED_EMAILS,
    },
    {
        "id": "",
        "question": (
            "Dans le modèle custom.purchase.request, quelles sont toutes "
            "les conditions vérifiées par action_valider ?"
        ),
        "expected_markers": [
            "purchase.group_purchase_manager",
            "__THRESHOLD__",
            "__GROUP_INSUFFICIENT__",
        ],
        "forbidden_markers": HARDCODED_EMAILS,
    },
    {
        "id": "",
        "question": (
            "Un utilisateur membre du groupe purchase_manager peut-il, à "
            "lui seul, valider n'importe quelle demande d'achat quel que "
            "soit son montant ?"
        ),
        "expected_markers": [
            "purchase.group_purchase_manager",
            "__THRESHOLD__",
            "__GROUP_INSUFFICIENT__",
        ],
        "forbidden_markers": HARDCODED_EMAILS,
    },
]


def check_raw_tool_output():
    print("=" * 80)
    print(f" RAW analyze_security_locks OUTPUT ({TARGET_MODEL})")
    print("=" * 80)
    G = get_code_intelligence_graph()
    set_graph_ref(G)
    tool_map = {t.name: t for t in ALL_CI_TOOLS}
    tool = tool_map.get("analyze_security_locks")
    if tool is None:
        print("[FAIL] Tool 'analyze_security_locks' not found in ALL_CI_TOOLS.")
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
        # gap (2026-08-10, module 4/8): this used to check for a
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


def check_e2e_full_pipeline():
    """Same questions as check_e2e(), but through query_graph() (the real
    route() dispatch) instead of calling code_intelligence_agent()
    directly -- catches routing bugs check_e2e() alone cannot see (see
    check_bloc9_01_credit_note_cascade_e2e.py::check_e2e_full_pipeline for
    the full rationale,  section 78). Generalized to all 8
    modules 2026-08-20."""
    print("=" * 80)
    print(" FULL PIPELINE (query_graph -> route())")
    print("=" * 80)
    all_ok = True
    for item in QUESTIONS:
        print(f"\n--- {item['id']} (full pipeline) ---")
        print(f"Question : {item['question']}")
        response = query_graph(question=item["question"], user_groups=[])
        answer = response.answer if response else ""
        print(f"R\u00e9ponse brute :\n{answer}\n")

        expected_markers = item.get("expected_markers", [])
        forbidden_markers = item.get("forbidden_markers", [])
        missing = [m for m in expected_markers if not _marker_present(m, answer)]
        present_forbidden = [m for m in forbidden_markers if _marker_present(m, answer)]
        for m in expected_markers:
            print(f"[{'OK ' if m not in missing else 'MISSING'}] expected marker: {m}")
        for m in forbidden_markers:
            print(f"[{'FAIL -- LEAKED' if m in present_forbidden else 'OK (masked)'}] forbidden marker: {m}")

        if missing or present_forbidden:
            print(f"[RESULT] {item['id']} (full pipeline): FAIL -- missing {missing}, leaked {present_forbidden}")
            all_ok = False
        else:
            print(f"[RESULT] {item['id']} (full pipeline): OK")
    return all_ok


def main():
    raw_ok = check_raw_tool_output()
    print()
    e2e_ok = check_e2e()
    print()
    full_pipeline_ok = check_e2e_full_pipeline()
    print("=" * 80)
    if raw_ok and e2e_ok and full_pipeline_ok:
        print("[ - 4/8] custom_purchase_request: E2E confirmed.")
        sys.exit(0)
    else:
        print("[ - 4/8] custom_purchase_request: GAP FOUND -- see [MISSING]/[FAIL] lines above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
