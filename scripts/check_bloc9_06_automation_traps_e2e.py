#!/usr/bin/env python3
"""
E2E verification for custom_automation_traps server action bypass.
"""

import re
import sys
import unicodedata
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.graph import code_intelligence_agent, get_code_intelligence_graph, query_graph, _get_admin_rpc_client
from code_intelligence.agent.ci_agent_node.context.agent_tools import ALL_CI_TOOLS, set_graph_ref
from code_intelligence.utils import SENSITIVE_BYPASS_MARKER

TARGET_MODEL = "account.move"


def _fold_accents(s: str) -> str:
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if not unicodedata.combining(c))


def _marker_present(marker: str, text: str) -> bool:
    return _fold_accents(marker.lower()) in _fold_accents(text.lower())


def _resolve_account_manager_group_id():
    """account.group_account_manager is a STANDARD Odoo group (module
    'account', not a custom_* module) -- same ir.model.data lookup
    technique as scripts/check_bloc9_02_credit_note_visibility_e2e.py's
    _resolve_group_ids() / run_adversarial_benchmark.py's
    _resolve_bloc7_test_group_ids(), just against a different module."""
    client, admin_uid = _get_admin_rpc_client()
    records = client.execute_kw(
        admin_uid, "ir.model.data", "search_read",
        [[("module", "=", "account"), ("name", "=", "group_account_manager")]],
        {"fields": ["res_id"]},
    )
    return records[0]["res_id"] if records else None


QUESTIONS = [
    {
        "id": "",
        "question": (
            "Est-ce que tous les avoirs fournisseurs passent par les "
            "mêmes règles d'approbation ?"
        ),
        "user_groups": [],
        # Anonymous requester: the bypass mechanism must be flagged as
        # EXISTING (something is being withheld) but its specifics (the
        # hardcoded IDs) must stay masked -- bis gating policy
        # working correctly. The trigger condition (in_refund) is
        # legitimate governance info, NOT gated (see design decision
        # 2026-08-11).
        "expected_markers": ["OMIS"],
        "forbidden_markers": ["42", "108", "231"],
    },
    {
        "id": "",
        "question": (
            "Est-ce que tous les avoirs fournisseurs passent par les "
            "mêmes règles d'approbation ?"
        ),
        "user_groups": "ACCOUNT_MANAGER",
        # With elevated access, the bypass mechanism is unredacted — no
        # gating footer is appended, so "sudo" only appears if the Groq
        # 8B LLM happens to include it in its paraphrase (not guaranteed,
        # confirmed by multiple runs). `in_refund` IS guaranteed by the
        # deterministic backfill. sudo() detail is separately validated
        # by 06c (focused question, same elevated access) where the LLM
        # consistently includes it.
        "expected_markers": ["in_refund"],
        "forbidden_markers": [],
    },
    {
        "id": "",
        "question": (
            "Dans le modèle account.move, quelles sont les conditions qui "
            "déclenchent l'action serveur automatisée définie par "
            "base.automation, et le mécanisme s'applique-t-il à tous les "
            "avoirs ou seulement à certains ?"
        ),
        "user_groups": "ACCOUNT_MANAGER",
        # Re-exercises the specific fix from this session: the enclosing
        # `if` condition must reach the final answer, not just the bare
        # "sudo() detected"/"hardcoded IDs detected" facts in isolation.
        "expected_markers": ["in_refund", "42"],
        "forbidden_markers": [],
    },
]


def check_raw_tool_output():
    print("=" * 80)
    print(f" RAW analyze_server_actions OUTPUT ({TARGET_MODEL})")
    print("=" * 80)
    G = get_code_intelligence_graph()
    set_graph_ref(G)
    tool_map = {t.name: t for t in ALL_CI_TOOLS}
    tool = tool_map.get("analyze_server_actions")
    if tool is None:
        print("[FAIL] Tool 'analyze_server_actions' not found in ALL_CI_TOOLS.")
        return False
    result = str(tool.invoke({"model_name": TARGET_MODEL}))
    print(result)
    print("-" * 80)

    checks_present = {
        "sudo() detected": "sudo",
        "hardcoded IDs": "42",
        "enclosing if-condition (in_refund)": "in_refund",
    }
    all_ok = True
    for label, marker in checks_present.items():
        present = _marker_present(marker, result)
        print(f"[{'OK ' if present else 'MISSING'}] raw tool mentions {label}: {marker!r}")
        if not present:
            all_ok = False

    tag_present = SENSITIVE_BYPASS_MARKER in result
    print(
        f"[{'OK ' if tag_present else 'FAIL'}] raw tool tags this bypass with "
        f"SENSITIVE_BYPASS_MARKER ({SENSITIVE_BYPASS_MARKER!r} present, pre-gating call)"
    )
    if not tag_present:
        all_ok = False

    return all_ok


def check_e2e(account_manager_group_id):
    all_ok = True
    for item in QUESTIONS:
        print("=" * 80)
        print(f" {item['id']}")
        print("=" * 80)
        print(f"Question: {item['question']}\n")

        raw_groups = item["user_groups"]
        if raw_groups == "ACCOUNT_MANAGER":
            if account_manager_group_id is None:
                print("[SKIP] account.group_account_manager DB id could not be resolved -- skipping.")
                continue
            user_groups = [account_manager_group_id]
        else:
            user_groups = raw_groups

        print(f"Requester groups: {user_groups}\n")
        state = {"question": item["question"], "chat_history": [], "user_groups": user_groups}
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
            print(f"[{'FAIL -- LEAK' if marker in present_forbidden else 'OK (absent)'}] forbidden marker: {marker}")

        if missing or present_forbidden:
            if missing:
                print(f"[RESULT] {item['id']}: INCOMPLETE -- missing {missing}")
            if present_forbidden:
                print(f"[RESULT] {item['id']}: LEAK -- forbidden marker(s) present {present_forbidden}")
            all_ok = False
        else:
            print(f"[RESULT] {item['id']}: all expected markers present, no forbidden markers.")
        print()
    return all_ok


def check_e2e_full_pipeline(account_manager_group_id):
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
        raw_groups = item["user_groups"]
        if raw_groups == "ACCOUNT_MANAGER":
            if account_manager_group_id is None:
                print(f"\n[SKIP] {item['id']} (full pipeline): account.group_account_manager DB id could not be resolved.")
                continue
            user_groups = [account_manager_group_id]
        else:
            user_groups = raw_groups

        print(f"\n--- {item['id']} (full pipeline) ---")
        print(f"Question : {item['question']}")
        print(f"Requester groups: {user_groups}")
        response = query_graph(question=item["question"], user_groups=user_groups)
        answer = response.answer if response else ""
        print(f"R\u00e9ponse brute :\n{answer}\n")

        expected_markers = item.get("expected_markers", [])
        forbidden_markers = item.get("forbidden_markers", [])
        missing = [m for m in expected_markers if not _marker_present(m, answer)]
        present_forbidden = [m for m in forbidden_markers if _marker_present(m, answer)]
        for m in expected_markers:
            print(f"[{'OK ' if m not in missing else 'MISSING'}] expected marker: {m}")
        for m in forbidden_markers:
            print(f"[{'FAIL -- LEAK' if m in present_forbidden else 'OK (absent)'}] forbidden marker: {m}")

        if missing or present_forbidden:
            print(f"[RESULT] {item['id']} (full pipeline): FAIL -- missing {missing}, leaked {present_forbidden}")
            all_ok = False
        else:
            print(f"[RESULT] {item['id']} (full pipeline): OK")
    return all_ok


def main():
    try:
        account_manager_group_id = _resolve_account_manager_group_id()
    except Exception as e:
        print(f"[WARN] Could not resolve account.group_account_manager via live Odoo RPC: {e}")
        account_manager_group_id = None
    if account_manager_group_id is None:
        print("[WARN] account.group_account_manager DB id not found -- "
              "06b/06c will be skipped (raw check + 06a still run).")

    raw_ok = check_raw_tool_output()
    print()
    e2e_ok = check_e2e(account_manager_group_id)
    print()
    full_pipeline_ok = check_e2e_full_pipeline(account_manager_group_id)
    print("=" * 80)
    if raw_ok and e2e_ok and full_pipeline_ok:
        print("[ - 6/8] custom_automation_traps: E2E confirmed.")
        sys.exit(0)
    else:
        print("[ - 6/8] custom_automation_traps: GAP FOUND -- see [MISSING]/[FAIL] lines above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
