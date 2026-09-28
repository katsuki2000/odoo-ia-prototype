#!/usr/bin/env python3
"""Diagnostic (section 989, lecture seule) : qui redige la reponse finale ?

Pour chaque question, journalise chaque appel a invoke_with_rate_limit de la
boucle ReAct (selection d'outils vs synthese) et si build_synthesis_prompt est
appele. Ne modifie rien sur le depot.

    python .scratch/diag_direct_answer_path.py MNT-Q2 PUR-Q2
"""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "scripts"))

import code_intelligence.agent.loop as loop_module
from run_bloc_n1_benchmark import build_agent_state, load_questions
from core.graph.graph import code_intelligence_agent
from core.evidence.evidence_collector import collect_and_clear_evidence, start_evidence_collection

_original_invoke = loop_module._invoke_with_rate_limit
_original_build = loop_module.build_synthesis_prompt
calls = []


def _describe(msg):
    tool_calls = getattr(msg, "tool_calls", None) or []
    content = getattr(msg, "content", "") or ""
    return {
        "tool_calls": [tc.get("name") for tc in tool_calls],
        "content_len": len(content),
        "content_head": content[:160].replace("\n", " "),
    }


def spy_invoke(llm, messages, *args, **kwargs):
    result = _original_invoke(llm, messages, *args, **kwargs)
    ai_msg = result[0] if isinstance(result, tuple) else result
    info = _describe(ai_msg)
    info["n_messages"] = len(messages)
    info["first_message_type"] = type(messages[0]).__name__ if messages else None
    calls.append(info)
    return result


def spy_build(*args, **kwargs):
    calls.append({"synthesis_prompt_built": True})
    return _original_build(*args, **kwargs)


loop_module._invoke_with_rate_limit = spy_invoke
loop_module.build_synthesis_prompt = spy_build

ids = sys.argv[1:] or ["MNT-Q2"]
questions, _ = load_questions(ids, None)
for item in questions:
    calls.clear()
    start_evidence_collection()
    try:
        code_intelligence_agent(build_agent_state(item))
    finally:
        collect_and_clear_evidence()
    print(f"\n=== {item['id']} : {len(calls)} evenement(s)")
    for i, c in enumerate(calls, 1):
        print(f"  [{i}] {c}")
    built = any(c.get("synthesis_prompt_built") for c in calls)
    direct = [c for c in calls if "content_len" in c and not c["tool_calls"] and c["content_len"] > 0]
    print(f"  -> synthese appelee: {built} | reponse directe du LLM de selection: {bool(direct) and not built}")
