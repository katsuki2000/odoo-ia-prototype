#!/usr/bin/env python3
"""
todo/contexte.txt section 499 -- Bug 3, hop-level instrumentation.

scripts/_diag_full_synthesis_500_leak.py (section 498) reproduced the "500"
paragraph 5/5 on the full code_intelligence_agent() pipeline, while every
isolated single-hop replay of the two known deterministic pre-dispatch hops
(analyze_security_locks, analyze_method_override_chain on account.move)
stayed clean 5/5 (sections 496-498). Section 499 established that, for this
exact question, exactly those same 2 hops fire deterministically -- so any
extra hop must come from the LLM-driven ReAct loop that runs afterwards
(up to CI_MAX_HOPS=4 total), which no prior diagnostic script ever captured.

This script reruns the same question through code_intelligence_agent() but
monkeypatches ReasoningTraceLogger.log_hop -- a read-only instrumentation
point that already receives the FULL, non-truncated observation text before
core/reasoning_trace_logger.py truncates it to 300 chars for the JSONL summary
(see log_hop's own observation_summary=(observation or "")[:300]) -- to
capture every hop actually executed this run, in order, with its tool name,
exact args, and complete observation text. No production code is modified;
the patch is undone in a finally block.

For each hop captured, the script re-runs the same amount-threshold regex
used by _backfill_missing_override_chain_amount (_OVERRIDE_CHAIN_AMOUNT_RE)
against that hop's own text in isolation, to pinpoint exactly which hop (if
any beyond the 2 known ones) introduces "500" -- rather than only observing
it in the final concatenated scoped_tool_output as the previous script did.
"""

import re
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.graph import code_intelligence_agent
from core.reasoning_trace_logger import ReasoningTraceLogger
from code_intelligence.ci_agent_node.helpers import _OVERRIDE_CHAIN_AMOUNT_RE

QUESTION = "Qui a le droit d'approuver un avoir pour un client VIP, et y a-t-il un piège dans le code ?"


def run_once(n: int) -> None:
    captured_hops = []
    original_log_hop = ReasoningTraceLogger.log_hop

    def _patched_log_hop(self, trace_id, hop_index, tool_name, tool_args, observation, elapsed_ms):
        captured_hops.append({
            "hop_index": hop_index,
            "tool_name": tool_name,
            "tool_args": dict(tool_args) if tool_args else {},
            "observation": observation,
        })
        return original_log_hop(self, trace_id, hop_index, tool_name, tool_args, observation, elapsed_ms)

    ReasoningTraceLogger.log_hop = _patched_log_hop
    try:
        state = {"question": QUESTION, "chat_history": [], "user_groups": []}
        res = code_intelligence_agent(state)
    finally:
        ReasoningTraceLogger.log_hop = original_log_hop

    print("=" * 80)
    print(f" TIRAGE {n} -- DIAG hop trace complet")
    print(f" Question: {QUESTION}")
    print("=" * 80)
    print(f"\nNombre de hops captures : {len(captured_hops)}\n")

    for hop in captured_hops:
        matches = _OVERRIDE_CHAIN_AMOUNT_RE.findall(hop["observation"] or "")
        flag = f"  <== MATCH(ES): {matches}" if matches else ""
        print(f"--- Hop {hop['hop_index']} : {hop['tool_name']}({hop['tool_args']}) ---{flag}")
        print(hop["observation"])
        print()

    answer_obj = res.get("response")
    verbatim_answer = answer_obj.answer if answer_obj else res.get("raw_answer", "Aucune reponse")
    print("--- REPONSE FINALE ---\n")
    print(verbatim_answer)
    print("\n" + "=" * 80 + "\n")


def main():
    n_runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    for i in range(1, n_runs + 1):
        run_once(i)


if __name__ == "__main__":
    main()
