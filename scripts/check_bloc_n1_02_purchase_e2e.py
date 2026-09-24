#!/usr/bin/env python3
"""
scripts/check_bloc_n1_02_purchase_e2e.py

Bloc N1 mechanical verification, 2/5 -- purchase module.
Mirrors the check_bloc9_0N_*.py pattern (raw/direct/full-pipeline)
against the ground truth from tests/native_n1_question_bank.json
(PUR-Q1 to PUR-Q5).

Ground truth (purchase module, 19 models / 8 rules / 38 ACL / 40 views):
  - PUR-Q1 security: ACLs identical for user/manager; real distinction is
    _approval_allowed() with po_double_validation_amount (default 5000).
  - PUR-Q2 workflow: button_confirm() -> _approval_allowed() -> button_approve()
    or state='to approve'.
  - PUR-Q3 inheritance: purchase.order is new; purchase extends account.move.
  - PUR-Q4 ui: button_approve has groups='purchase.group_purchase_manager'.
  - PUR-Q5 constraints: _unlink_if_cancelled on order, _unlink_except_purchase_
    or_done on lines, _sql_constraints on lines.
"""

import re
import sys
import unicodedata
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.graph.graph import code_intelligence_agent, get_code_intelligence_graph, query_graph
from code_intelligence.agent.tools import ALL_CI_TOOLS
from code_intelligence.agent.tool_helpers import set_graph_ref


def _fold_accents(s: str) -> str:
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if not unicodedata.combining(c))


def _normalize_ws(s: str) -> str:
    return re.sub(r'\s+', '', s)


def _marker_present(marker: str, text: str) -> bool:
    m = _fold_accents(marker.lower())
    t = _fold_accents(text.lower())
    if m in t:
        return True
    return _normalize_ws(m) in _normalize_ws(t)


def _word_boundary_present(marker: str, text: str) -> bool:
    return re.search(
        r'(?<![A-Za-z0-9_])' + re.escape(marker) + r'(?![A-Za-z0-9_])', text
    ) is not None


QUESTIONS = [
    {
        "id": "PUR-Q1",
        "question": (
            "L'ACL de purchase.order accorde les 4 permissions "
            "(lecture/ecriture/creation/suppression) a group_purchase_user "
            "comme a group_purchase_manager. Qu'est-ce qui distingue alors "
            "reellement un simple acheteur d'un manager sur une commande d'achat ?"
        ),
        "expected_markers": [
            "_approval_allowed",
            "po_double_validation",
            "group_purchase_manager",
        ],
        "expected_markers_word_boundary": [],
        "forbidden_markers": [],
    },
    {
        "id": "PUR-Q2",
        "question": (
            "Que se passe-t-il exactement quand on clique sur 'Confirm Order' "
            "(button_confirm) selon que la commande est eligible ou non a "
            "l'approbation directe ?"
        ),
        "expected_markers": [
            "button_confirm",
            "_approval_allowed",
            "button_approve",
            "to approve",
        ],
        "expected_markers_word_boundary": [],
        "forbidden_markers": [],
    },
    {
        "id": "PUR-Q3",
        "question": (
            "purchase.order est-il un nouveau modele ou une extension ? "
            "Le module purchase modifie-t-il en parallele un modele natif "
            "deja existant hors de son propre domaine (achat), et comment ?"
        ),
        "expected_markers": [
            "account.move",
        ],
        "expected_markers_word_boundary": [
            "purchase.order",
        ],
        "forbidden_markers": [],
    },
    {
        "id": "PUR-Q4",
        "question": (
            "Pourquoi le bouton 'Approve Order' n'est-il pas visible pour "
            "un utilisateur simple meme quand la commande est au statut "
            "'to approve' ?"
        ),
        "expected_markers": [
            "button_approve",
            "group_purchase_manager",
        ],
        "expected_markers_word_boundary": [],
        "forbidden_markers": [],
    },
    {
        "id": "PUR-Q5",
        "question": (
            "Quelles regles empechent de supprimer une commande d'achat ou "
            "une de ses lignes selon leur etat, et quelle contrainte SQL "
            "distincte s'applique sur les lignes elles-memes ?"
        ),
        "expected_markers": [
            "_unlink_if_cancelled",
            "cancel",
        ],
        "expected_markers_word_boundary": [],
        "forbidden_markers": [],
    },
]


def check_raw_tool_output():
    print("=" * 80)
    print(" RAW who_has_access_to OUTPUT (purchase.order)")
    print("=" * 80)
    G = get_code_intelligence_graph()
    set_graph_ref(G)
    tool_map = {t.name: t for t in ALL_CI_TOOLS}
    tool = tool_map.get("who_has_access_to")
    if tool is None:
        print("[FAIL] Tool 'who_has_access_to' not found in ALL_CI_TOOLS.")
        return False
    result = str(tool.invoke({"model_name": "purchase.order"}))
    print(result)
    print("-" * 80)

    checks = {
        "ACL purchase order (user)": "access_purchase_order",
        "ACL purchase order (manager)": "access_purchase_order_manager",
        "group_purchase_manager": "group_purchase_manager",
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

        plain_markers = item.get("expected_markers", [])
        wb_markers = item.get("expected_markers_word_boundary", [])
        forbidden_markers = item.get("forbidden_markers", [])

        missing = [m for m in plain_markers if not _marker_present(m, answer)]
        missing += [m for m in wb_markers if not _word_boundary_present(m, answer)]
        present_forbidden = [m for m in forbidden_markers if _marker_present(m, answer)]

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


def check_e2e_full_pipeline():
    print("=" * 80)
    print(" FULL PIPELINE (query_graph -> route()) -- purchase module")
    print("=" * 80)
    all_ok = True

    cases = [
        {
            "label": "PUR-Q1 (full pipeline)",
            "question": (
                "Qu'est-ce qui distingue un simple acheteur d'un manager "
                "pour approuver une commande d'achat ?"
            ),
            "expected_markers": ["_approval_allowed", "group_purchase_manager"],
            "forbidden_markers": [],
        },
        {
            "label": "PUR-Q4 (full pipeline)",
            "question": (
                "Pourquoi le bouton Approve Order n'est-il pas visible "
                "pour un acheteur simple ?"
            ),
            "expected_markers": ["group_purchase_manager"],
            "forbidden_markers": [],
        },
    ]

    for case in cases:
        print(f"\n--- {case['label']} ---")
        print(f"Question : {case['question']}")
        response = query_graph(question=case["question"], user_groups=[])
        answer = response.answer if response else ""
        print(f"Reponse brute :\n{answer}\n")

        missing = [m for m in case["expected_markers"] if not _marker_present(m, answer)]
        present_forbidden = [m for m in case["forbidden_markers"] if _marker_present(m, answer)]
        for m in case["expected_markers"]:
            print(f"[{'OK ' if m not in missing else 'MISSING'}] expected marker: {m}")
        for m in case["forbidden_markers"]:
            print(f"[{'FAIL' if m in present_forbidden else 'OK '}] forbidden marker absent: {m}")

        if missing or present_forbidden:
            print(f"[RESULT] {case['label']}: FAIL -- missing {missing}, forbidden present {present_forbidden}")
            all_ok = False
        else:
            print(f"[RESULT] {case['label']}: OK")

    return all_ok


def main():
    raw_ok = check_raw_tool_output()
    print()
    e2e_ok = check_e2e()
    print()
    full_pipeline_ok = check_e2e_full_pipeline()
    print("=" * 80)
    if raw_ok and e2e_ok and full_pipeline_ok:
        print("[ - 2/5] purchase: E2E confirmed.")
        sys.exit(0)
    else:
        print("[ - 2/5] purchase: GAP FOUND -- see [MISSING]/[FAIL] lines above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
