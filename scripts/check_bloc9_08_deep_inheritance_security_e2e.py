#!/usr/bin/env python3
"""
E2E verification for custom_deep_inheritance_security.
"""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.graph.graph import code_intelligence_agent, get_code_intelligence_graph, query_graph
from code_intelligence.agent.ci_agent_node.context.agent_tools import ALL_CI_TOOLS, set_graph_ref
from code_intelligence.knowledge_rules.deterministic.access.group_resolver import _fold_accents

TARGET_MODEL = "custom.deep.document"


def _marker_present(marker: str, text: str) -> bool:
    """Check if marker is present in text, with space-normalization for
    numeric markers (e.g. "50000" must also match "50 000€", "50 000",
    "50\u00a0000" in French-formatted text).  Without this, 08b was a false
    negative: the response cited only the French format, not the raw
    Python literal, and the naive `in` check failed."""
    m = marker.lower()
    t = text.lower()
    if m in t:
        return True
    # Normalize all whitespace (including non-breaking space) out of both
    # sides and retry -- catches "50 000" vs "50000", "100 000" vs "100000".
    import re
    t_nospace = re.sub(r'\s+', '', t)
    m_nospace = re.sub(r'\s+', '', m)
    return m_nospace in t_nospace


QUESTIONS = [
    {
        "id": "",
        # Amount (60000) clears the Level2 threshold (50000) but NOT the
        # Level5 threshold (100000) -- only account.group_account_manager
        # should be named, never base.group_system (the double-threshold
        # conflation trap, same shape as module 1).
        "question": (
            "Qui a le droit de valider un document à 60 000€ dans le "
            "modèle custom.deep.document (module de sécurité à héritage "
            "profond) ?"
        ),
        "expected_markers": ["account.group_account_manager", "50000"],
        "forbidden_markers": [],
    },
    {
        "id": "",
        "question": (
            "Dans le modèle custom.deep.document, quelles sont toutes les "
            "méthodes qui contiennent une vérification has_group, et à "
            "partir de quel montant chacune s'applique-t-elle ?"
        ),
        "expected_markers": [
            "50000",
            "100000",
            "account.group_account_manager",
            "base.group_system",
        ],
        "forbidden_markers": [],
    },
    {
        "id": "",
        "question": (
            "Un utilisateur standard (groupe de base uniquement) dont "
            "l'entreprise est différente de celle du document peut-il "
            "voir un document custom.deep.document de 30 000€ appartenant "
            "à un autre utilisateur, sachant que 30 000€ est sous le seuil "
            "de 50 000€ ?"
        ),
        "expected_markers": ["NE PEUT PAS"],
        "forbidden_markers": [],
    },
]


def check_raw_tool_output():
    print("=" * 80)
    print(f" RAW analyze_security_locks + evaluate_record_rules OUTPUT ({TARGET_MODEL})")
    print("=" * 80)
    G = get_code_intelligence_graph()
    set_graph_ref(G)
    tool_map = {t.name: t for t in ALL_CI_TOOLS}
    all_ok = True

    lock_tool = tool_map.get("analyze_security_locks")
    if lock_tool is None:
        print("[FAIL] Tool 'analyze_security_locks' not found in ALL_CI_TOOLS.")
        all_ok = False
    else:
        lock_result = str(lock_tool.invoke({"model_name": TARGET_MODEL}))
        print(lock_result)
        print("-" * 80)

        for marker, label in [
            ("account.group_account_manager", "Level2 required group"),
            ("base.group_system", "Level5 required group"),
            ("50000", "Level2 threshold amount"),
            ("100000", "Level5 threshold amount"),
        ]:
            if marker in lock_result:
                print(f"[OK ] raw lock tool mentions {label}: '{marker}'")
            else:
                print(f"[MISSING] raw lock tool does NOT mention {label}: '{marker}'")
                all_ok = False

    rule_tool = tool_map.get("evaluate_record_rules")
    if rule_tool is None:
        print("[FAIL] Tool 'evaluate_record_rules' not found in ALL_CI_TOOLS.")
        all_ok = False
    else:
        rule_result = str(
            rule_tool.invoke({
                "model_name": TARGET_MODEL,
                "user_groups_json": "[\"base.group_user\"]",
                "permission": "read",
            })
        )
        print(rule_result)
        print("-" * 80)

        if "cantonnement" in rule_result.lower():
            print("[OK ] raw rule tool mentions the global company-cantonment rule")
        else:
            print("[MISSING] raw rule tool does NOT mention the global company-cantonment rule")
            all_ok = False

        if "50000" in rule_result or "50 000" in rule_result:
            print("[OK ] raw rule tool mentions the nested rule's 50000 threshold")
        else:
            print("[MISSING] raw rule tool does NOT mention the nested rule's 50000 threshold")
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
            status = "OK " if marker not in missing else "MISSING"
            print(f"[{status}] expected marker: {marker}")

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


def _marker_present_full_pipeline(marker: str, text: str) -> bool:
    """Accent/case-insensitive substring check for the full-pipeline pass."""
    return _fold_accents(marker.lower()) in _fold_accents(text.lower())


def check_e2e_full_pipeline():
    """Same intent as check_e2e(), but through query_graph() (the real
    route() dispatch) instead of calling code_intelligence_agent()
    directly -- catches routing bugs the direct call cannot see (see the
    equivalent note in check_bloc9_01_credit_note_cascade_e2e.py). Also
    carries two company/threshold combinations the original check_e2e()
    didn't cover (same company below threshold; different company above
    the group threshold), to confirm can_view_amount_v2 doesn't invert
    on either edge once routed through the real pipeline. Merged in
    2026-08-20 from the now-deleted
    miro-rag/scripts/check_bloc9_08_deep_inheritance_security_e2e.py
    reconstruction  rather than kept as a
    second, diverging script.
    """
    print("=" * 80)
    print(" FULL PIPELINE (query_graph -> route()) -- can_view_amount_v2 edge cases")
    print("=" * 80)
    all_ok = True

    cases = [
        {
            "label": "08a-business (full pipeline, 60k)",
            "question": (
                "Qui a le droit de valider un document \u00e0 60 000\u20ac dans le "
                "mod\u00e8le custom.deep.document (module de s\u00e9curit\u00e9 \u00e0 h\u00e9ritage "
                "profond) ?"
            ),
            "expected_markers": ["account.group_account_manager"],
            "forbidden_markers": ["n'a pas le droit de valider"],
        },
        {
            "label": "08c-nested-domain-trap (full pipeline, autre soci\u00e9t\u00e9, 30k)",
            "question": (
                "Un utilisateur d'une autre soci\u00e9t\u00e9 peut-il voir un enregistrement "
                "custom.deep.document de 30000\u20ac appartenant \u00e0 une soci\u00e9t\u00e9 "
                "diff\u00e9rente de la sienne ?"
            ),
            "expected_markers": ["NE PEUT PAS"],
            "forbidden_markers": ["PEUT voir cet enregistrement"],
        },
        {
            "label": "m\u00eame soci\u00e9t\u00e9, sous le seuil de groupe (30k) -- doit rester visible",
            "question": "Un utilisateur de la m\u00eame soci\u00e9t\u00e9 peut-il voir un enregistrement custom.deep.document de 30000\u20ac ?",
            "expected_markers": ["PEUT"],
            "forbidden_markers": ["NE PEUT PAS"],
        },
        {
            "label": "08c bis -- autre soci\u00e9t\u00e9, montant \u00e9lev\u00e9 (80k, au-del\u00e0 du seuil de groupe)",
            "question": (
                "Un utilisateur d'une autre soci\u00e9t\u00e9 peut-il consulter un "
                "enregistrement custom.deep.document de 80000\u20ac appartenant \u00e0 "
                "une soci\u00e9t\u00e9 diff\u00e9rente de la sienne ?"
            ),
            "expected_markers": ["NE PEUT PAS"],
            "forbidden_markers": ["a le droit de voir", "peut consulter"],
        },
    ]

    for case in cases:
        print(f"\n--- {case['label']} ---")
        print(f"Question : {case['question']}")
        response = query_graph(question=case["question"], user_groups=[])
        answer = response.answer if response else ""
        print(f"R\u00e9ponse brute :\n{answer}\n")

        missing = [m for m in case["expected_markers"] if not _marker_present_full_pipeline(m, answer)]
        present_forbidden = [m for m in case["forbidden_markers"] if _marker_present_full_pipeline(m, answer)]
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
        print("[ - 8/8] custom_deep_inheritance_security: E2E confirmed.")
        sys.exit(0)
    else:
        print("[ - 8/8] custom_deep_inheritance_security: GAP FOUND -- see [MISSING]/[FAIL] lines above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
