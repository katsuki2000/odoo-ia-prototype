#!/usr/bin/env python3
"""
scripts/check_bloc9_06_automation_traps_e2e.py

Bloc 9 generalization check, 6/8 -- same method as modules 1/8-5/8
(raw composite-tool output isolated from synthesis, then live end-to-end
through code_intelligence_agent()), applied to the sixth mechanism:
custom_automation_traps, a server-action-based bypass using sudo() and
hardcoded partner IDs in an ir.actions.server code field, triggered by
a base.automation on account.move (on_create_or_write).

Ground truth (custom_automation_traps/data/automation_rule.xml, read
directly from disk):
  - Server action `ir_action_server_avoir_fournisseur_privilegie`:
    FOURNISSEURS_PRIVILEGIES = [42, 108, 231]
    for rec in records:
        if rec.move_type == 'in_refund' and rec.partner_id.id in FOURNISSEURS_PRIVILEGIES:
            rec.sudo().action_post()
  - base.automation `base_automation_avoir_fournisseur_privilegie`:
    trigger=on_create_or_write, targets account.move, fires the above
    server action.

  The trap (Q5.1): the question asks "est-ce que TOUS les avoirs
  fournisseurs passent par les mêmes règles d'approbation ?" -- correct
  answer is NON. Only `in_refund` moves (supplier credit notes) from
  partners 42, 108, 231 get auto-validated via sudo(), bypassing all
  normal approval rules. The fix we're verifying (Bloc 9, 10/08) is
  that server_action_analyzer.py now captures the enclosing `if`
  condition (move_type == 'in_refund') in `trigger_conditions` and
  surfaces it in both security_warnings and summary_text -- without
  this, the tool reported "sudo() detected" and "hardcoded IDs [42,
  108, 231]" as flat, unlinked facts with no mention of when the bypass
  actually fires, making it impossible to answer Q5.1 correctly.

  No Python models in this module (empty __init__.py) -- no
  `analyser_verrous_securite` check needed, only `analyser_actions_serveur`.
  No live Odoo group resolution needed (the bypass is partner-ID-based,
  not group-based).
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

# The server action targets account.move (via model_id ref="account.model_account_move")
TARGET_MODEL = "account.move"


def _fold_accents(s: str) -> str:
    """Normalize accented characters for marker matching -- the server
    action code drops French accents ('fournisseurs privilegies'), while
    the synthesis LLM may re-accent when paraphrasing."""
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if not unicodedata.combining(c))


def _marker_present(marker: str, text: str) -> bool:
    return _fold_accents(marker.lower()) in _fold_accents(text.lower())


QUESTIONS = [
    {
        "id": "bloc9-06a-business",
        # This is Q5.1 verbatim from BENCHMARK_QUESTIONS
        "question": (
            "Est-ce que tous les avoirs fournisseurs passent par les "
            "mêmes règles d'approbation ?"
        ),
        # The answer must say NO and mention the specific partners + the
        # fact that it's conditional (in_refund / not all credit notes).
        "expected_markers": ["sudo", "42", "108", "231"],
        "forbidden_markers": [],
    },
    {
        "id": "bloc9-06b-technical",
        "question": (
            "Quelles actions serveur (ir.actions.server) ou règles "
            "automatisées (base.automation) existent sur le modèle "
            "account.move, et que font-elles ?"
        ),
        "expected_markers": ["sudo", "42", "108", "231"],
        "forbidden_markers": [],
    },
    {
        "id": "bloc9-06c-condition-trap",
        # Trap: asks specifically whether ALL supplier credit notes are
        # auto-validated. Correct answer: NO, only those from the 3
        # hardcoded partner IDs. The guard `in_refund` must be surfaced.
        "question": (
            "Les avoirs fournisseurs de TOUS les partenaires sont-ils "
            "automatiquement validés par une action serveur, ou "
            "seulement certains ?"
        ),
        "expected_markers": ["42", "108", "231"],
        "forbidden_markers": [],
    },
]


def check_raw_tool_output():
    """Call analyser_actions_serveur directly and verify it surfaces
    sudo, hardcoded IDs, SENSITIVE_BYPASS_MARKER, and -- critically --
    the enclosing if-condition (in_refund)."""
    print("=" * 80)
    print(f" RAW analyser_actions_serveur OUTPUT ({TARGET_MODEL})")
    print("=" * 80)
    G = get_code_intelligence_graph()
    set_graph_ref(G)
    tool_map = {t.name: t for t in ALL_CI_TOOLS}
    tool = tool_map.get("analyser_actions_serveur")
    if tool is None:
        print("[FAIL] Tool 'analyser_actions_serveur' not found in ALL_CI_TOOLS.")
        return False
    result = str(tool.invoke({"model_name": TARGET_MODEL}))
    print(result)
    print("-" * 80)

    all_ok = True

    # 1. sudo() must be detected
    if "sudo" in result.lower():
        print("[OK ] raw tool mentions sudo()")
    else:
        print("[MISSING] raw tool does NOT mention sudo()")
        all_ok = False

    # 2. Hardcoded IDs [42, 108, 231] must be present
    for pid in ["42", "108", "231"]:
        if pid in result:
            print(f"[OK ] raw tool mentions partner ID {pid}")
        else:
            print(f"[MISSING] raw tool does NOT mention partner ID {pid}")
            all_ok = False

    # 3. SENSITIVE_BYPASS_MARKER must be present (sudo + hardcoded IDs
    #    are genuine bypass mechanisms, not ordinary governance)
    if SENSITIVE_BYPASS_MARKER in result:
        print(f"[OK ] raw tool tags output with {SENSITIVE_BYPASS_MARKER!r}")
    else:
        print(f"[MISSING] raw tool does NOT tag output with {SENSITIVE_BYPASS_MARKER!r}")
        all_ok = False

    # 4. THE FIX WE'RE VERIFYING: the enclosing if-condition must be
    #    surfaced so that Q5.1 can answer "NON, pas tous les avoirs" --
    #    the bypass only fires for in_refund moves from 3 partners.
    if "in_refund" in result:
        print("[OK ] raw tool mentions 'in_refund' trigger condition (THE FIX)")
    else:
        print("[MISSING] raw tool does NOT mention 'in_refund' -- guard capture fix NOT working")
        all_ok = False

    # 5. The "Condition(s) de déclenchement" summary line should be present
    if _marker_present("condition", result) and _marker_present("declenchement", result):
        print("[OK ] raw tool includes 'Condition(s) de déclenchement' summary line")
    else:
        print("[MISSING] raw tool does NOT include trigger condition summary line")
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

        # Check expected markers
        expected_markers = item.get("expected_markers", [])
        missing = [m for m in expected_markers if not _marker_present(m, answer)]
        for marker in expected_markers:
            status = "OK " if marker not in missing else "MISSING"
            print(f"[{status}] expected marker: {marker}")

        # Check forbidden markers
        forbidden_markers = item.get("forbidden_markers", [])
        found_forbidden = [m for m in forbidden_markers if _marker_present(m, answer)]
        for marker in forbidden_markers:
            status = "FAIL" if marker in found_forbidden else "OK "
            print(f"[{status}] forbidden marker absent: {marker}")

        if missing or found_forbidden:
            print(f"[RESULT] {item['id']}: INCOMPLETE -- missing {missing}, forbidden {found_forbidden}")
            all_ok = False
        else:
            print(f"[RESULT] {item['id']}: all expected markers present.")
        print()
    return all_ok


def main():
    raw_ok = check_raw_tool_output()
    print()
    e2e_ok = check_e2e()
    print("=" * 80)
    if raw_ok and e2e_ok:
        print("[BLOC 9 - 6/8] custom_automation_traps: E2E confirmed.")
        sys.exit(0)
    else:
        print("[BLOC 9 - 6/8] custom_automation_traps: GAP FOUND -- see [MISSING]/[FAIL] lines above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
