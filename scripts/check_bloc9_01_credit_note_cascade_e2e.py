#!/usr/bin/env python3
"""
scripts/check_bloc9_01_credit_note_cascade_e2e.py

Bloc 9 generalization check, 1/8 -- replicates the check_j34_35_e2e.py
method (live end-to-end run through code_intelligence_agent(), not just
the isolated extraction-layer tests) on the "cascade avoirs" mechanism:
custom_credit_note_approval (base) + custom_credit_note_approval_regional
+ custom_credit_note_approval_vip, three modules that override the same
action_valider_avoir() on account.move in sequence.

This mechanism is already exercised by scripts/run_adversarial_benchmark.py
(Q1.1/Q1.2), so the pipeline itself is known to work with the *business*
phrasing used there. What that fixed benchmark does NOT check, and what
this script adds, following the J34-35 method:

  1. The RAW observation of the composite tool that actually does the
     cascade analysis (analyser_chaine_surcharge_methode), isolated from
     the synthesis LLM -- same split as check_locks_raw.py, to catch a
     tool-level gap before blaming synthesis for dropping a fact.
  2. A question phrased with the bare technical model name ("account.move")
     instead of a business alias, to specifically re-exercise the
     exact_technical_mention resolver path that J34-35 found silently
     broken for custom.deep.document. account.move is a core Odoo model
     so this is a weaker signal than for a purely custom model name, but
     it still confirms the forced dispatch to analyser_chaine_surcharge_
     methode survives when the model is named literally rather than via
     the "avoir" business alias.

Ground truth (models/account_move.py in each of the 3 modules):
  - base: amount_total > 5000 requires account.group_account_manager,
    else UserError "Seul un responsable comptable peut valider un avoir
    de plus de 5000€."
  - regional: amount_total > 20000 -> avoir_directeur_regional_id set to
    self.env.user.employee_id.parent_id.parent_id.user_id (N+2), business
    rule undocumented anywhere else than in this code.
  - vip: partner_id.avoir_vip_exempt -> direct validation, no threshold,
    but the module calls super().action_valider_avoir() AFTER already
    handling the VIP case with `continue` in its own loop -- structural
    trap flagged in real_plan.md ("piège: super() rappelé sur tout le
    recordset a la fin").
"""

import re
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "miro-rag"))

from rag.graph import code_intelligence_agent, get_code_intelligence_graph
from code_intelligence.ci_agent_tools import ALL_CI_TOOLS, set_graph_ref

QUESTIONS = [
    {
        "id": "bloc9-01a-business",
        "question": "Qui a le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) ?",
        "expected_markers": [
            "account.group_account_manager",
            "20000",
        ],
    },
    {
        "id": "bloc9-01b-technical",
        "question": (
            "Dans le modèle account.move, quelles sont toutes les surcharges de "
            "la méthode action_valider_avoir et dans quel ordre s'exécutent-elles ?"
        ),
        # Word-boundary markers, not bare substrings: a 2026-08-07 live run
        # produced a hallucinated 4th module "custom_credit_note_approval_
        # global" that the sourcing guard correctly flagged as unverified,
        # but the old substring check for "custom_credit_note_approval"
        # matched INSIDE that fabricated name and silently reported [OK].
        "expected_markers": [
            "custom_credit_note_approval_regional",
            "custom_credit_note_approval_vip",
        ],
        "expected_markers_word_boundary": [
            "custom_credit_note_approval",
        ],
        "forbidden_markers": [
            "custom_credit_note_approval_global",
        ],
    },
    {
        "id": "bloc9-01c-vip-trap",
        "question": "Qui a le droit d'approuver un avoir pour un client VIP, et y a-t-il un piège dans le code ?",
        "expected_markers": [
            "avoir_vip_exempt",
            "super()",
        ],
    },
]


def check_raw_tool_output():
    print("=" * 80)
    print(" RAW analyser_chaine_surcharge_methode OUTPUT (account.move / action_valider_avoir)")
    print("=" * 80)
    G = get_code_intelligence_graph()
    set_graph_ref(G)
    tool_map = {t.name: t for t in ALL_CI_TOOLS}
    tool = tool_map.get("analyser_chaine_surcharge_methode")
    if tool is None:
        print("[FAIL] Tool 'analyser_chaine_surcharge_methode' not found in ALL_CI_TOOLS.")
        return False
    result = tool.invoke({"model_name": "account.move", "method_name": "action_valider_avoir"})
    print(result)
    print("-" * 80)
    modules = ["custom_credit_note_approval", "custom_credit_note_approval_regional",
               "custom_credit_note_approval_vip"]
    all_present = all(m in result for m in modules)
    for m in modules:
        print(f"[{'OK ' if m in result else 'MISSING'}] raw tool mentions module: {m}")
    return all_present


def _word_boundary_present(marker: str, text: str) -> bool:
    """Match marker as a whole token, not as a substring of a longer
    identifier -- plain `in` checks let a hallucinated module name like
    'custom_credit_note_approval_global' silently satisfy the marker
    'custom_credit_note_approval' (found live, 2026-08-07)."""
    return re.search(r'(?<![A-Za-z0-9_])' + re.escape(marker) + r'(?![A-Za-z0-9_])', text) is not None


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

        plain_markers = item.get("expected_markers", [])
        wb_markers = item.get("expected_markers_word_boundary", [])
        forbidden_markers = item.get("forbidden_markers", [])

        missing = [m for m in plain_markers if m not in answer]
        missing += [m for m in wb_markers if not _word_boundary_present(m, answer)]
        present_forbidden = [m for m in forbidden_markers if _word_boundary_present(m, answer)]

        for marker in plain_markers:
            print(f"[{'OK ' if marker not in missing else 'MISSING'}] expected marker: {marker}")
        for marker in wb_markers:
            print(f"[{'OK ' if marker not in missing else 'MISSING'}] expected marker (word-boundary): {marker}")
        for marker in forbidden_markers:
            print(f"[{'FAIL -- HALLUCINATED' if marker in present_forbidden else 'OK (absent)'}] forbidden marker: {marker}")

        if missing or present_forbidden:
            if missing:
                print(f"[RESULT] {item['id']}: INCOMPLETE -- missing {missing}")
            if present_forbidden:
                print(f"[RESULT] {item['id']}: HALLUCINATION -- forbidden marker(s) present {present_forbidden}")
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
        print("[BLOC 9 - 1/8] custom_credit_note_approval(+regional+vip): E2E confirmed.")
        sys.exit(0)
    else:
        print("[BLOC 9 - 1/8] custom_credit_note_approval(+regional+vip): GAP FOUND -- see [MISSING] lines above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
