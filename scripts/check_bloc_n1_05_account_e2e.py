#!/usr/bin/env python3
"""
scripts/check_bloc_n1_05_account_e2e.py

Bloc N1 mechanical verification, 5/5 -- account module.
Mirrors the check_bloc9_0N_*.py pattern (raw/direct/full-pipeline)
against the ground truth from tests/native_n1_question_bank.json
(ACC-Q1 to ACC-Q5).

Ground truth (account module, 90 models / 31 rules / 163 ACL / 131 views):
  - ACC-Q1 security: access_account_move_manager is read-only, but
    group_account_manager has implied_ids=[group_account_invoice] which
    gives full CRUD via access_account_move_uinvoice.
  - ACC-Q2 workflow: _check_fiscalyear_lock_date() blocks everyone, the
    group only changes the error message text.
  - ACC-Q3 inheritance: account.move is new; account extends res.partner
    adding fiscal_country_codes.
  - ACC-Q4 ui: account_id has groups='account.group_account_readonly',
    neither group_account_invoice nor group_account_manager imply it.
  - ACC-Q5 constraints: _sql_constraints unique_name has empty SQL def;
    real uniqueness via _auto_init() CREATE UNIQUE INDEX (partial).
"""

import re
import sys
import unicodedata
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.graph.graph import code_intelligence_agent, get_code_intelligence_graph, query_graph
from code_intelligence.agent.tools import ALL_CI_TOOLS
from code_intelligence.agent.tools.helpers import set_graph_ref


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
        "id": "ACC-Q1",
        "question": (
            "L'ACL directe de account.group_account_manager sur account.move "
            "n'accorde que perm_read=1 (aucune ecriture/creation/suppression). "
            "Un 'Billing Administrator' (group_account_manager) peut-il malgre "
            "tout creer et modifier des factures ?"
        ),
        "expected_markers": [
            "implied_ids",
            "group_account_invoice",
            "access_account_move",
        ],
        "expected_markers_word_boundary": [],
        "forbidden_markers": [],
    },
    {
        "id": "ACC-Q2",
        "question": (
            "Un 'Billing Administrator' (group_account_manager) peut-il poster "
            "une ecriture comptable dont la date est anterieure ou egale a la "
            "date de cloture (lock date) de la societe ?"
        ),
        "expected_markers": [
            "_check_fiscalyear_lock_date",
            "lock_date",
        ],
        "expected_markers_word_boundary": [],
        "forbidden_markers": [],
    },
    {
        "id": "ACC-Q3",
        "question": (
            "account.move est-il un nouveau modele ou une extension ? Le "
            "module account etend-il en parallele un modele natif hors de "
            "son propre perimetre comptable ?"
        ),
        "expected_markers": [
            "res.partner",
        ],
        "expected_markers_word_boundary": [
            "account.move",
        ],
        "forbidden_markers": [],
    },
    {
        "id": "ACC-Q4",
        "question": (
            "Un utilisateur avec uniquement group_account_invoice ('Billing') "
            "voit-il le compte comptable (account_id) d'une ligne de facture ? "
            "Et un 'Billing Administrator' (group_account_manager) le voit-il, "
            "en configuration Invoicing seule (sans le module Accounting "
            "installe) ?"
        ),
        "expected_markers": [
            "group_account_readonly",
            "account_id",
        ],
        "expected_markers_word_boundary": [],
        "forbidden_markers": [],
    },
    {
        "id": "ACC-Q5",
        "question": (
            "account.move declare un _sql_constraints 'unique_name' dont la "
            "definition SQL est une chaine vide -- comment l'unicite du numero "
            "de piece est-elle reellement appliquee ?"
        ),
        "expected_markers": [
            "_auto_init",
            "unique_name",
        ],
        "expected_markers_word_boundary": [],
        "forbidden_markers": [],
    },
]


def check_raw_tool_output():
    print("=" * 80)
    print(" RAW who_has_access_to OUTPUT (account.move)")
    print("=" * 80)
    G = get_code_intelligence_graph()
    set_graph_ref(G)
    tool_map = {t.name: t for t in ALL_CI_TOOLS}
    tool = tool_map.get("who_has_access_to")
    if tool is None:
        print("[FAIL] Tool 'who_has_access_to' not found in ALL_CI_TOOLS.")
        return False
    result = str(tool.invoke({"model_name": "account.move"}))
    print(result)
    print("-" * 80)

    checks = {
        "ACL account move": "access_account_move",
        "group_account_manager": "group_account_manager",
        "group_account_invoice": "group_account_invoice",
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
    print(" FULL PIPELINE (query_graph -> route()) -- account module")
    print("=" * 80)
    all_ok = True

    cases = [
        {
            "label": "ACC-Q1 (full pipeline)",
            "question": (
                "Un Billing Administrator peut-il creer des factures malgre "
                "son ACL en lecture seule sur account.move ?"
            ),
            "expected_markers": ["implied_ids", "group_account_invoice"],
            "forbidden_markers": [],
        },
        {
            "label": "ACC-Q5 (full pipeline)",
            "question": (
                "Comment l'unicite du numero de piece comptable est-elle "
                "reellement appliquee dans account.move ?"
            ),
            "expected_markers": ["_auto_init", "unique"],
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
        print("[ - 5/5] account: E2E confirmed.")
        sys.exit(0)
    else:
        print("[ - 5/5] account: GAP FOUND -- see [MISSING]/[FAIL] lines above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
