#!/usr/bin/env python3
"""
scripts/check_bloc9_06b_isolation_in_refund.py

Isolation rerun for the gap diagnosed in todo/contexte.txt section 582:
check_bloc9_06_automation_traps_e2e.py's check_e2e_full_pipeline() failed
on question "Est-ce que tous les avoirs fournisseurs passent par les
memes regles d'approbation ?" (groups=[account.group_account_manager]) --
`in_refund` missing from the synthesized answer, correlated with a 429
Inference rate-limit hit during interpret_server_action_with_llm() right
before that run.

This script re-runs ONLY that one question, through query_graph()
(full pipeline, same as the failing check), N times in a row, to
distinguish:
  - a real synthesis regression (in_refund missing repeatedly,
    independent of rate-limit events) from
  - a one-off degradation artifact correlated with rate limiting
    (suspect-flaky, same class as module 08a).

No conclusion is drawn here -- just repeated raw evidence to paste back.
"""

import sys
import unicodedata
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.graph.graph import query_graph, _get_admin_rpc_client

N_RUNS = 5

QUESTION = (
    "Est-ce que tous les avoirs fournisseurs passent par les "
    "mêmes règles d'approbation ?"
)


def _fold_accents(s: str) -> str:
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if not unicodedata.combining(c))


def _marker_present(marker: str, text: str) -> bool:
    return _fold_accents(marker.lower()) in _fold_accents(text.lower())


def _resolve_account_manager_group_id():
    client, admin_uid = _get_admin_rpc_client()
    records = client.execute_kw(
        admin_uid, "ir.model.data", "search_read",
        [[("module", "=", "account"), ("name", "=", "group_account_manager")]],
        {"fields": ["res_id"]},
    )
    return records[0]["res_id"] if records else None


def main():
    try:
        group_id = _resolve_account_manager_group_id()
    except Exception as e:
        print(f"[FAIL] Could not resolve account.group_account_manager: {e}")
        sys.exit(1)
    if group_id is None:
        print("[FAIL] account.group_account_manager DB id not found.")
        sys.exit(1)

    user_groups = [group_id]
    results = []

    for i in range(1, N_RUNS + 1):
        print("=" * 80)
        print(f" RUN {i}/{N_RUNS}")
        print("=" * 80)
        response = query_graph(question=QUESTION, user_groups=user_groups)
        answer = response.answer if response else ""
        print(answer)
        print("-" * 80)
        present = _marker_present("in_refund", answer)
        print(f"[{'OK ' if present else 'MISSING'}] in_refund present this run")
        results.append(present)
        print()

    print("=" * 80)
    print(" SUMMARY")
    print("=" * 80)
    ok_count = sum(results)
    print(f"in_refund present in {ok_count}/{N_RUNS} runs -> {results}")
    if ok_count == N_RUNS:
        print("[RESULT] Stable across isolation reruns -- likely was a one-off rate-limit artifact.")
    elif ok_count == 0:
        print("[RESULT] Missing in ALL isolation reruns -- likely a real synthesis regression, not flakiness.")
    else:
        print("[RESULT] Inconsistent across reruns -- flaky, needs further investigation (rate-limit correlation?).")


if __name__ == "__main__":
    main()
