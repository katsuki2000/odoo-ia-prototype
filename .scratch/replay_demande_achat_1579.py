import json, sys, time
sys.path.insert(0, '.')
sys.argv = ['x']
import scripts.run_agent_variants_bench as bench
import code_intelligence.agent.loop as agentLoop
from core.evidence.evidence_collector import collect_and_clear_evidence, start_evidence_collection
from core.session.reasoning_trace_logger import ReasoningTraceLogger
from unittest import mock

bench.warm_up()
summaries = []
start_evidence_collection()
t0 = time.time()
with bench.capture_summaries(summaries):
    result = agentLoop.code_intelligence_agent({'question': "comment faire une demande d'achat ?", 'chat_history': [], 'language': 'fr'})
collect_and_clear_evidence()
s = summaries[-1] if summaries else None
print('SECONDES', round(time.time() - t0, 1))
print('SUMMARY', s.hop_count if s else None, s.llm_call_count if s else None, s.fallback_reason if s else None)
print('RESULT_KEYS', list(result.keys()) if isinstance(result, dict) else type(result))
text = result.get('final_answer') or result.get('answer') or json.dumps(result, ensure_ascii=False, default=str)[:3000]
print('ANSWER\n', text[:3500])
