#!/usr/bin/env python3
"""
scripts/check_bloc_n1_01_maintenance_e2e.py

Bloc N1 mechanical verification, 1/5 -- maintenance module.
Mirrors the check_bloc9_0N_*.py pattern (raw/direct/full-pipeline)
against the ground truth from tests/native_n1_question_bank.json
(MNT-Q1 to MNT-Q5).

Ground truth (maintenance module, 7 models / 8 rules / 10 ACL / 25 views):
  - MNT-Q1 security: ACL access_equipment_user (read-only for base.group_user),
    equipment_rule_user restricts to message_partner_ids followers.
  - MNT-Q2 workflow: write() detects stage_id -> done=True for preventive
    recurring requests, duplicates with new schedule_date.
  - MNT-Q3 inheritance: maintenance.equipment is a new model, inherits
    maintenance.mixin (AbstractModel).
  - MNT-Q4 ui: cost field has groups='maintenance.group_equipment_manager'.
  - MNT-Q5 constraints: serial_no unique SQL, _check_repeat_interval Python.
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
        "id": "MNT-Q1",
        "question": (
            "Un utilisateur simple (base.group_user, sans group_equipment_manager) "
            "peut-il modifier une fiche equipement (maintenance.equipment), et "
            "quels equipements peut-il seulement consulter ?"
        ),
        "expected_markers": [
            "access_equipment_user",
            "group_equipment_manager",
            "message_partner_ids",
        ],
        "expected_markers_word_boundary": [],
        "forbidden_markers": [],
    },
    {
        "id": "MNT-Q2",
        "question": (
            "Que se passe-t-il automatiquement quand une demande de maintenance "
            "preventive et recurrente (recurring_maintenance=True) atteint une "
            "etape marquee 'done' ?"
        ),
        "expected_markers": [
            "recurring_maintenance",
            "schedule_date",
            "repeat_interval",
        ],
        "expected_markers_word_boundary": [],
        "forbidden_markers": [],
    },
    {
        "id": "MNT-Q3",
        "question": (
            "maintenance.equipment est-il une extension d'un modele natif Odoo "
            "existant, ou un nouveau modele ? Quel role joue maintenance.mixin "
            "dont il herite ?"
        ),
        "expected_markers": [
            "maintenance.mixin",
            "mail.thread",
        ],
        "expected_markers_word_boundary": [],
        "forbidden_markers": [],
    },
    {
        "id": "MNT-Q4",
        "question": (
            "Pourquoi le champ 'cost' (cout) d'un equipement n'est-il pas "
            "visible pour tous les utilisateurs ayant acces en lecture a sa fiche ?"
        ),
        "expected_markers": [
            "group_equipment_manager",
            "cost",
        ],
        "expected_markers_word_boundary": [],
        "forbidden_markers": [],
    },
    {
        "id": "MNT-Q5",
        "question": (
            "Quelle regle empeche de creer deux equipements avec le meme numero "
            "de serie, et quelle contrainte distincte s'applique sur l'intervalle "
            "de repetition (repeat_interval) d'une demande recurrente ?"
        ),
        "expected_markers": [
            "serial_no",
            "unique",
            "repeat_interval",
        ],
        "expected_markers_word_boundary": [],
        "forbidden_markers": [],
    },
]


def check_raw_tool_output():
    print("=" * 80)
    print(" RAW who_has_access_to OUTPUT (maintenance.equipment)")
    print("=" * 80)
    G = get_code_intelligence_graph()
    set_graph_ref(G)
    tool_map = {t.name: t for t in ALL_CI_TOOLS}
    tool = tool_map.get("who_has_access_to")
    if tool is None:
        print("[FAIL] Tool 'who_has_access_to' not found in ALL_CI_TOOLS.")
        return False
    result = str(tool.invoke({"model_name": "maintenance.equipment"}))
    print(result)
    print("-" * 80)

    checks = {
        "ACL read-only for user": "access_equipment_user",
        "ACL admin/manager": "access_equipment_admin_user",
        "group_equipment_manager": "group_equipment_manager",
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
    print(" FULL PIPELINE (query_graph -> route()) -- maintenance module")
    print("=" * 80)
    all_ok = True

    cases = [
        {
            "label": "MNT-Q1 (full pipeline)",
            "question": (
                "Quels equipements un utilisateur simple (sans "
                "group_equipment_manager) peut-il consulter dans la maintenance ?"
            ),
            "expected_markers": ["message_partner_ids", "equipment_rule_user"],
            "forbidden_markers": [],
        },
        {
            "label": "MNT-Q5 (full pipeline)",
            "question": (
                "Quelles contraintes empechent de creer un equipement "
                "avec un numero de serie deja existant ?"
            ),
            "expected_markers": ["serial_no", "unique"],
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
        print("[ - 1/5] maintenance: E2E confirmed.")
        sys.exit(0)
    else:
        print("[ - 1/5] maintenance: GAP FOUND -- see [MISSING]/[FAIL] lines above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
