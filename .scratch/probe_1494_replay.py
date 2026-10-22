import sys, json, time, logging
sys.path.insert(0, '.')
logging.basicConfig(level=logging.WARNING)
from code_intelligence.agent import loop
from core.evidence import start_evidence_collection, collect_and_clear_evidence
calls, replies = [], []
orig_exec = loop.execute_tool_calls
def spy_exec(ctx, response, messages, *a, **k):
    for c in response.tool_calls:
        calls.append((c['name'], json.dumps(c['args'], ensure_ascii=False)[:300]))
    out = orig_exec(ctx, response, messages, *a, **k)
    calls.append(('  -> observation', (messages[-1].content or '')[:400].replace('\n', ' ')))
    return out
loop.execute_tool_calls = spy_exec
orig_inv = loop.invoke_with_rate_limit
def spy_inv(model, messages, **k):
    r, w = orig_inv(model, messages, **k)
    replies.append((len(messages), [t['name'] for t in (getattr(r, 'tool_calls', None) or [])], (r.content or '')[:300].replace('\n', ' ')))
    return r, w
loop.invoke_with_rate_limit = spy_inv
question = sys.argv[1] if len(sys.argv) > 1 else "qui s’occupe d’approuver les demandes de mise à disposition ?"
state = {"question": question, "chat_history": [], "language": "fr"}
t = time.time()
start_evidence_collection()
try:
    res = loop.code_intelligence_agent(state)
finally:
    collect_and_clear_evidence()
print('DUREE', round(time.time() - t, 1), 's')
print('TOURS LLM:', len(replies))
for r in replies: print('  tour', r)
print('APPELS OUTILS:', len([c for c in calls if not c[0].startswith('  ')]))
for c in calls: print('  ', c)
ans = res.get('response')
print('REPONSE:', (ans.answer if ans else res.get('raw_answer'))[:700])
