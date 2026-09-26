#!/usr/bin/env python3
"""
scripts/check_bloc_n1_03_sale_e2e.py

Bloc N1 mechanical verification, 3/5 -- sale module.
Mirrors the check_bloc9_0N_*.py pattern (raw/direct/full-pipeline)
against the ground truth from tests/native_n1_question_bank.json
(SAL-Q1 to SAL-Q5).

Ground truth (sale module, 35 models / 27 rules / 54 ACL / 55 views):
  - SAL-Q1 security: sale_order_personal_rule restricts simple salesperson
    to user_id-assigned or unassigned orders; portal rules via
    message_partner_ids.
  - SAL-Q2 workflow: action_confirm() -> _should_be_locked() checks
    group_auto_done_setting on the order creator.
  - SAL-Q3 inheritance: sale.order is new; sale module extends account.move.
  - SAL-Q4 ui: action_unlock has groups='sales_team.group_sale_manager'.
  - SAL-Q5 constraints: date_order_conditional_required SQL CHECK,
    _check_prepayment_percent Python.
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
        "id": "SAL-Q1",
        "question": (
            "Un vendeur (sales_team.group_sale_salesman, sans "
            "group_sale_salesman_all_leads) peut-il voir toutes les commandes "
            "de vente de son entreprise, ou seulement certaines ? Et un "
            "utilisateur du portail (base.group_portal) ?"
        ),
        "security_principals": {
            "salesperson": {"group_xmlids": ["sales_team.group_sale_salesman"]},
            "portal_user": {"group_xmlids": ["base.group_portal"]},
        },
        "expected_markers": [],
        "expected_markers_word_boundary": [],
        # Section 946: these are raw ir.rule/field technical identifiers --
        # per architecture.md's "Double niveau d'explication", they belong
        # to the verification level (response.sources, the dépliant), not
        # to the user-level prose (response.answer). Checked against the
        # concatenated sources text instead -- see check_e2e().
        "expected_markers_sources": [
            "sale_order_personal_rule",
            "user_id",
        ],
        "forbidden_markers": [],
    },
    {
        "id": "SAL-Q2",
        "question": (
            "Que se passe-t-il exactement quand on confirme une commande de "
            "vente (action_confirm), et dans quel cas est-elle automatiquement "
            "verrouillee (locked) juste apres ?"
        ),
        "expected_markers": [
            "action_confirm",
            "locked",
        ],
        "expected_markers_word_boundary": [],
        "forbidden_markers": [],
    },
    {
        "id": "SAL-Q3",
        "question": (
            "sale.order est-il un nouveau modele ou une extension ? Quel modele "
            "natif hors du perimetre 'vente' ce module etend-il directement, "
            "et sous quel nom de classe ?"
        ),
        "expected_markers": [
            "account.move",
        ],
        "expected_markers_word_boundary": [
            "sale.order",
        ],
        "forbidden_markers": [],
    },
    {
        "id": "SAL-Q4",
        "question": (
            "Pourquoi un vendeur simple ne peut-il pas deverrouiller (Unlock) "
            "une commande verrouillee, meme si c'est lui qui l'a confirmee ?"
        ),
        "expected_markers": [
            "action_unlock",
            "group_sale_manager",
        ],
        "expected_markers_word_boundary": [],
        "forbidden_markers": [],
    },
    {
        "id": "SAL-Q5",
        "question": (
            "Quelle contrainte empeche une commande confirmee de ne pas avoir "
            "de date de confirmation, et quelle contrainte distincte s'applique "
            "sur le pourcentage d'acompte demande (prepayment_percent) ?"
        ),
        "expected_markers": [
            "date_order",
            "prepayment_percent",
        ],
        "expected_markers_word_boundary": [],
        "forbidden_markers": [],
    },
]


def check_raw_tool_output():
    print("=" * 80)
    print(" RAW who_has_access_to OUTPUT (sale.order)")
    print("=" * 80)
    G = get_code_intelligence_graph()
    set_graph_ref(G)
    tool_map = {t.name: t for t in ALL_CI_TOOLS}
    tool = tool_map.get("who_has_access_to")
    if tool is None:
        print("[FAIL] Tool 'who_has_access_to' not found in ALL_CI_TOOLS.")
        return False
    result = str(tool.invoke({"model_name": "sale.order"}))
    print(result)
    print("-" * 80)

    # Section 946: who_has_access_to exposes group xml_ids + an active-rule
    # COUNT, never the ACL row's own xml_id nor individual ir.rule names --
    # those come from evaluate_record_rules (checked in check_e2e() against
    # response.sources instead). The two markers below match what this
    # specific tool actually emits.
    checks = {
        "vendeur group": "sales_team.group_sale_salesman",
        "active rules count": "Active Rules:",
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
        if item.get("security_principals"):
            state["security_principals"] = item["security_principals"]
        result = code_intelligence_agent(state)
        response = result.get("response")
        if response is None:
            print("[FAIL] No response object returned.")
            all_ok = False
            continue
        answer = response.answer
        sources_text = "\n\n".join(s.snippet or "" for s in (response.sources or []))
        timing = result.get("timing", {})
        print(f"Answer (hops={timing.get('ci_hop_count', '?')}):\n{answer}\n")
        print("-" * 80)

        plain_markers = item.get("expected_markers", [])
        wb_markers = item.get("expected_markers_word_boundary", [])
        source_markers = item.get("expected_markers_sources", [])
        forbidden_markers = item.get("forbidden_markers", [])

        missing = [m for m in plain_markers if not _marker_present(m, answer)]
        missing += [m for m in wb_markers if not _word_boundary_present(m, answer)]
        missing += [m for m in source_markers if not _marker_present(m, sources_text)]
        present_forbidden = [m for m in forbidden_markers if _marker_present(m, answer)]

        for marker in plain_markers:
            print(f"[{'OK ' if marker not in missing else 'MISSING'}] expected marker: {marker}")
        for marker in wb_markers:
            print(f"[{'OK ' if marker not in missing else 'MISSING'}] expected marker (word-boundary): {marker}")
        for marker in source_markers:
            print(f"[{'OK ' if marker not in missing else 'MISSING'}] expected marker (sources/dépliant): {marker}")
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
    print(" FULL PIPELINE (query_graph -> route()) -- sale module")
    print("=" * 80)
    all_ok = True

    cases = [
        {
            "label": "SAL-Q1 (full pipeline)",
            "question": (
                "Un simple vendeur peut-il voir toutes les commandes de vente ?"
            ),
            # Section 946: technical identifiers live in response.sources
            # (verification level), not in the user-level prose -- see the
            # same note on QUESTIONS[0] above.
            "expected_markers": [],
            "expected_markers_sources": ["sale_order_personal_rule", "user_id"],
            "forbidden_markers": [],
        },
        {
            "label": "SAL-Q4 (full pipeline)",
            "question": (
                "Pourquoi un vendeur ne peut-il pas deverrouiller une "
                "commande de vente ?"
            ),
            "expected_markers": ["group_sale_manager"],
            "forbidden_markers": [],
        },
    ]

    for case in cases:
        print(f"\n--- {case['label']} ---")
        print(f"Question : {case['question']}")
        response = query_graph(question=case["question"], user_groups=[])
        answer = response.answer if response else ""
        sources_text = "\n\n".join(s.snippet or "" for s in ((response.sources if response else None) or []))
        print(f"Reponse brute :\n{answer}\n")

        missing = [m for m in case["expected_markers"] if not _marker_present(m, answer)]
        missing += [m for m in case.get("expected_markers_sources", []) if not _marker_present(m, sources_text)]
        present_forbidden = [m for m in case["forbidden_markers"] if _marker_present(m, answer)]
        for m in case["expected_markers"]:
            print(f"[{'OK ' if m not in missing else 'MISSING'}] expected marker: {m}")
        for m in case.get("expected_markers_sources", []):
            print(f"[{'OK ' if m not in missing else 'MISSING'}] expected marker (sources/dépliant): {m}")
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
        print("[ - 3/5] sale: E2E confirmed.")
        sys.exit(0)
    else:
        print("[ - 3/5] sale: GAP FOUND -- see [MISSING]/[FAIL] lines above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
