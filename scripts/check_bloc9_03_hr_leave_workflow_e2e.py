#!/usr/bin/env python3
"""
scripts/check_bloc9_03_hr_leave_workflow_e2e.py

 generalization check, 3/8 -- same method as
check_bloc9_01_credit_note_cascade_e2e.py / check_bloc9_02_credit_note_
visibility_e2e.py (raw composite-tool output isolated from synthesis,
then live end-to-end through code_intelligence_agent()), applied to the
third mechanism: custom_hr_leave_workflow, a two-layer Python security
lock on hr.leave (Q2.1 of scripts/run_adversarial_benchmark.py).

Unlike module 2/8 (ir.rule OR combination), this mechanism needs no real
requester group identity -- Q2.1 asks a generic "why can't I validate"
question, not "can THIS specific person view/approve", so no live Odoo
group resolution is needed here. Also unlike module 1/8 (three modules
overriding the same method in cascade), this is a single custom module
extending ONE core Odoo addon (hr_holidays) that is a full, real Odoo
core module on disk here -- not a addons/ stand-in -- so this
script is also an implicit re-confirmation that the J36 generic
direct-dependency loading fix (core/graph.py::get_code_intelligence_graph,
"Load each custom_* module's DIRECT manifest dependencies too") still
picks up hr_holidays for custom_hr_leave_workflow, the same way it was
fixed to pick up hr_expense for custom_expense_risk_base.

Ground truth (custom_hr_leave_workflow/models/hr_leave.py, read directly
from disk, not from real / text):
  - `_check_solde_conge` (api.constrains): if number_of_days > solde AND
    NOT conge_urgence, raise ValidationError telling the user to check
    'Demande urgente' to submit for exceptional N+2 validation instead.
    This is the FIRST gate -- checking 'urgente' bypasses THIS one.
  - `action_approve`: if conge_urgence AND number_of_days > solde, the
    approver must be either the N+2 (employee_id.parent_id.parent_id.
    user_id) or a member of hr_holidays.group_hr_holidays_manager --
    otherwise raise a SECOND ValidationError: "Une demande urgente
    depassant le solde doit etre validee par le N+2 ou un responsable
    RH." (source has no French accents, same class of accent mismatch as
    module 2/8's rule names -- the small synthesis LLM re-accents when
    paraphrasing, so marker matching here is accent-insensitive too, same
    _fold_accents/_marker_present technique, not reinvented).
  - The trap this question is actually testing: checking 'urgente' does
    NOT mean the request validates automatically -- it only lets the
    request THROUGH the first gate (the solde constraint) and INTO a
    second, separate approval gate (N+2 or HR manager) that a regular
    manager cannot clear. A user reading only the first message could
    wrongly conclude checking the box is sufficient.

Q2.1 itself carries no "user_groups" key in BENCHMARK_QUESTIONS (unlike
Q6.1/Q6.2) -- run as an ungrouped/anonymous requester, same as module
1/8's questions.
"""

import sys
import unicodedata
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.graph.graph import code_intelligence_agent, get_code_intelligence_graph, query_graph
from code_intelligence.agent.tools import ALL_CI_TOOLS
from code_intelligence.agent.tool_helpers import set_graph_ref

TARGET_MODEL = "hr.leave"


def _fold_accents(s: str) -> str:
    """Same rationale as check_bloc9_02_credit_note_visibility_e2e.py's
    _fold_accents -- the raw exception message in hr_leave.py is written
    without French accents ('depassant', 'etre', 'validee'), but the small
    synthesis LLM may re-accent it correctly in prose when paraphrasing
    ('dépassant', 'être', 'validée'). A plain substring check against the
    unaccented source form would then report a false MISSING on an
    otherwise-correct answer."""
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if not unicodedata.combining(c))


def _marker_present(marker: str, text: str) -> bool:
    return _fold_accents(marker.lower()) in _fold_accents(text.lower())


QUESTIONS = [
    {
        "id": "",
        "question": (
            "Pourquoi je n'arrive pas à valider ma demande de congé alors "
            "que j'ai coché 'urgente' ?"
        ),
        "expected_markers": [
            "N+2",
            "responsable RH",
            "hr_holidays.group_hr_holidays_manager",
        ],
    },
    {
        "id": "",
        "question": (
            "Dans le modèle hr.leave, quels sont tous les verrous "
            "de validation d'une demande de congé ?"
        ),
        "expected_markers": [
            "solde de conges restant",
            "N+2 ou un responsable RH",
        ],
    },
    {
        "id": "",
        "question": (
            "Si un employé coche 'urgente' sur une demande de congé qui "
            "dépasse son solde restant, sa demande est-elle automatiquement "
            "validée, ou faut-il encore une validation supplémentaire ?"
        ),
        "expected_markers": [
            "N+2",
            "hr_holidays.group_hr_holidays_manager",
        ],
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

    checks = {
        "exception message (solde constraint)": "solde de conges restant",
        "exception message (N+2/RH approval gate)": "N+2 ou un responsable RH",
        "required group (has_group extraction)": "hr_holidays.group_hr_holidays_manager",
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
        missing = [m for m in expected_markers if not _marker_present(m, answer)]

        for marker in expected_markers:
            print(f"[{'OK ' if marker not in missing else 'MISSING'}] expected marker: {marker}")

        if missing:
            print(f"[RESULT] {item['id']}: INCOMPLETE -- missing {missing}")
            all_ok = False
        else:
            print(f"[RESULT] {item['id']}: all expected markers present.")
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
        missing = [m for m in expected_markers if not _marker_present(m, answer)]
        for m in expected_markers:
            print(f"[{'OK ' if m not in missing else 'MISSING'}] expected marker: {m}")

        if missing:
            print(f"[RESULT] {item['id']} (full pipeline): FAIL -- missing {missing}")
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
        print("[ - 3/8] custom_hr_leave_workflow: E2E confirmed.")
        sys.exit(0)
    else:
        print("[ - 3/8] custom_hr_leave_workflow: GAP FOUND -- see [MISSING]/[FAIL] lines above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
