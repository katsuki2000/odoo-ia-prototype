#!/usr/bin/env python3
"""
scripts/check_bloc9_06_automation_traps_e2e.py

Bloc 9 generalization check, 6/8 -- same method as modules 1/8-5/8 (raw
composite-tool output isolated from synthesis, then live end-to-end
through code_intelligence_agent()), applied to the sixth mechanism:
custom_automation_traps (Q5.1), a data-driven ir.actions.server / sudo()
bypass -- structurally different again from modules 1/8-5/8: the risky
logic lives in an XML `code` field (base.automation trigger), not in
Python module source, so it goes through server_action_analyzer.py /
analyser_actions_serveur, never analyser_verrous_securite.

Ground truth (custom_automation_traps/data/automation_rule.xml, read
directly from disk, not from real plan.md/etat_reel.md text):
  - A base.automation rule on account.move (on_create_or_write) invokes
    an ir.actions.server whose code is:
        FOURNISSEURS_PRIVILEGIES = [42, 108, 231]
        for rec in records:
            if rec.move_type == 'in_refund' and rec.partner_id.id in FOURNISSEURS_PRIVILEGIES:
                rec.sudo().action_post()
  - i.e. avoirs fournisseurs (in_refund moves) from 3 hardcoded partner
    IDs are auto-posted via sudo(), bypassing EVERY approval mechanism
    from module 1/8's cascade (has_group threshold, N+2 relational chain,
    VIP exemption) entirely -- sudo() ignores ir.rule/ACL, and this
    server action runs before any of those checks would even apply.
    Q5.1's answer is NON: not all avoirs follow the same rules.
  - This IS a genuine security bypass (sudo() + hardcoded privileged IDs),
    not ordinary governance -- both get SENSITIVE_BYPASS_MARKER-tagged at
    the source (server_action_analyzer.py) and are subject to Bloc 7-bis
    gating (authorization_gate.py) exactly like modules 1/8's/4/8's
    has_group()-derived thresholds are NOT gated, but their hardcoded
    email/ID lists ARE. `_has_elevated_access` for account.move uses the
    model's OWN has_group() source signal (J25-26 fix) -- which, thanks
    to module 1/8's Gap 1 fix (has_group() extraction), now resolves to
    `account.group_account_manager` (from custom_credit_note_approval).
    So: an ANONYMOUS requester should see the bypass mechanism's EXISTENCE
    (a redacted line naming the category) but NOT its specifics (42, 108,
    231); the trigger condition (`in_refund`) is governance info visible
    to all (not tagged SENSITIVE_BYPASS_MARKER). A requester WITH
    account.group_account_manager should
    see everything, matching Q5.1's literal benchmark "expected" text.
  - Real, non-application-code gap fixed earlier in this same session
    (2026-08-11), confirmed by another instance also on disk: sudo()/
    hardcoded-ID detection in server_action_analyzer.py previously
    reported flat, unlinked facts with no record of the enclosing `if`
    condition scoping them -- `_find_enclosing_if_condition` +
    `trigger_conditions` now attach "rec.move_type == 'in_refund' and
    rec.partner_id.id in FOURNISSEURS_PRIVILEGIES" to both the sudo AND
    the hardcoded-ID warnings. This script's raw check asserts that fix
    holds end-to-end (via the real @tool wrapper, not just the unit-level
    analyze_server_action_code() call already covered by
    test_s2_3_server_actions.py::test_full_adversarial_code_q5_1).
"""

import re
import sys
import unicodedata
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "miro-rag"))

from rag.graph import code_intelligence_agent, get_code_intelligence_graph, query_graph, _get_admin_rpc_client
from code_intelligence.ci_agent_tools import ALL_CI_TOOLS, set_graph_ref
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
        "id": "bloc9-06a-anonymous-masked",
        "question": (
            "Est-ce que tous les avoirs fournisseurs passent par les "
            "mêmes règles d'approbation ?"
        ),
        "user_groups": [],
        # Anonymous requester: the bypass mechanism must be flagged as
        # EXISTING (something is being withheld) but its specifics (the
        # hardcoded IDs) must stay masked -- Bloc 7-bis gating policy
        # working correctly. The trigger condition (in_refund) is
        # legitimate governance info, NOT gated (see design decision
        # 2026-08-11).
        "expected_markers": ["OMIS"],
        "forbidden_markers": ["42", "108", "231"],
    },
    {
        "id": "bloc9-06b-privileged-full-detail",
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
        "id": "bloc9-06c-technical-condition-capture",
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
    the full rationale, contexte.txt section 78). Generalized to all 8
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
        print("[BLOC 9 - 6/8] custom_automation_traps: E2E confirmed.")
        sys.exit(0)
    else:
        print("[BLOC 9 - 6/8] custom_automation_traps: GAP FOUND -- see [MISSING]/[FAIL] lines above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
