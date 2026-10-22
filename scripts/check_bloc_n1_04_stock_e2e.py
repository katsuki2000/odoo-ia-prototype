#!/usr/bin/env python3
"""
scripts/check_bloc_n1_04_stock_e2e.py

Bloc N1 mechanical verification, 4/5 -- stock module.
Mirrors the check_bloc9_0N_*.py pattern (raw/direct/full-pipeline)
against the ground truth from tests/native_n1_question_bank.json
(STK-Q1 to STK-Q5).

Ground truth (stock module, 75 models / 16 rules / 91 ACL / 128 views):
  - STK-Q1 security: access_stock_quant_all gives read-only to base.group_user;
    access_stock_move_line_all gives full CRUD to base.group_user.
  - STK-Q2 workflow: button_validate() with backorder logic depending on
    picking_type_id.create_backorder setting.
  - STK-Q3 inheritance: stock.picking is new; stock extends product.product
    adding qty_available/virtual_available.
  - STK-Q4 ui: location fields have groups='stock.group_stock_multi_locations'
    (configuration-activated, not a role group).
  - STK-Q5 constraints: 3 @api.constrains on stock.quant + _check_unique_lot
    on stock.lot.
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
        "id": "STK-Q1",
        "question": (
            "Un simple employe (base.group_user, sans stock.group_stock_user) "
            "peut-il consulter les quantites en stock (stock.quant) ? Et "
            "peut-il modifier une ligne de mouvement (stock.move.line) ?"
        ),
        "expected_markers": [
            "access_stock_quant_all",
            "perm_read",
            "stock.move.line",
        ],
        "expected_markers_word_boundary": [],
        "forbidden_markers": [],
    },
    {
        "id": "STK-Q2",
        "question": (
            "Que se passe-t-il quand on valide un transfert de stock "
            "(button_validate) dont les quantites traitees sont inferieures "
            "aux quantites demandees ?"
        ),
        "expected_markers": [
            "button_validate",
            "backorder",
            "create_backorder",
        ],
        "expected_markers_word_boundary": [],
        "forbidden_markers": [],
    },
    {
        "id": "STK-Q3",
        "question": (
            "stock.picking est-il un nouveau modele ou une extension ? Le "
            "module stock etend-il en parallele un modele natif hors de son "
            "propre perimetre, et avec quels champs cles ?"
        ),
        "expected_markers": [
            "product.product",
            "qty_available",
        ],
        "expected_markers_word_boundary": [
            "stock.picking",
        ],
        "forbidden_markers": [],
    },
    {
        "id": "STK-Q4",
        "question": (
            "Pourquoi les champs 'From'/'To' (emplacement source/destination) "
            "n'apparaissent-ils pas sur un transfert de stock pour la plupart "
            "des utilisateurs ?"
        ),
        "expected_markers": [
            "group_stock_multi_locations",
        ],
        "expected_markers_word_boundary": [],
        "forbidden_markers": [],
    },
    {
        "id": "STK-Q5",
        "question": (
            "Quelles contraintes empechent la creation d'un stock.quant "
            "invalide, et quelle regle distincte garantit l'unicite d'un "
            "numero de serie ?"
        ),
        "expected_markers": [
            "check_product_id",
            "check_location_id",
            "check_lot_id",
        ],
        "expected_markers_word_boundary": [],
        "forbidden_markers": [],
    },
]


def check_raw_tool_output():
    print("=" * 80)
    print(" RAW who_has_access_to OUTPUT (stock.quant)")
    print("=" * 80)
    G = get_code_intelligence_graph()
    set_graph_ref(G)
    tool_map = {t.name: t for t in ALL_CI_TOOLS}
    tool = tool_map.get("who_has_access_to")
    if tool is None:
        print("[FAIL] Tool 'who_has_access_to' not found in ALL_CI_TOOLS.")
        return False
    result = str(tool.invoke({"model_name": "stock.quant"}))
    print(result)
    print("-" * 80)

    checks = {
        "ACL stock quant (all users)": "access_stock_quant_all",
        "base.group_user": "base.group_user",
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
    print(" FULL PIPELINE (query_graph -> route()) -- stock module")
    print("=" * 80)
    all_ok = True

    cases = [
        {
            "label": "STK-Q1 (full pipeline)",
            "question": (
                "Un employe sans stock.group_stock_user peut-il consulter "
                "les quantites en stock ?"
            ),
            "expected_markers": ["access_stock_quant_all", "perm_read"],
            "forbidden_markers": [],
        },
        {
            "label": "STK-Q4 (full pipeline)",
            "question": (
                "Pourquoi les emplacements source et destination ne sont "
                "pas visibles sur un transfert de stock ?"
            ),
            "expected_markers": ["group_stock_multi_locations"],
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
        print("[ - 4/5] stock: E2E confirmed.")
        sys.exit(0)
    else:
        print("[ - 4/5] stock: GAP FOUND -- see [MISSING]/[FAIL] lines above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
