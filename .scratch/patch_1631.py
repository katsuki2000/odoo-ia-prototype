from pathlib import Path


def edit(path, pairs):
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    for old, new in pairs:
        assert text.count(old) == 1, (path, old[:70])
        text = text.replace(old, new)
    p.write_text(text, encoding="utf-8")


def cut(path, start, end):
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    assert text.count(start) == 1 and text.count(end) == 1, (path, start[:40])
    i, j = text.index(start), text.index(end)
    assert i < j
    p.write_text(text[:i] + text[j:], encoding="utf-8")


cut("core/schemas.py", "    resolved_concept: Optional[dict]", "    verification: Optional[VerificationReport]")
edit("core/state.py", [
    ("    resolved_concept: Optional[dict]\n", ""),
    ("    evidence_status: Optional[str]\n", ""),
    ("    investigation_plan: Optional[dict]\n", ""),
])
edit("core/graph/graph.py", [("'last_route': last_route, 'investigation_plan': None,", "'last_route': last_route,")])
edit("core/graph/graph_nodes.py", [
    ("'retrieved_chunks': [], 'investigation_plan': None}", "'retrieved_chunks': []}"),
    ("        response.resolved_concept = state.get('resolved_concept')\n"
     "        response.evidence_status = state.get('evidence_status')\n"
     "        response.investigation_plan = state.get('investigation_plan')\n", ""),
])
edit("core/routing/routing.py", [
    ("    result = {'route': decision, 'timing': timing,\n              'resolved_concept': None, 'investigation_plan': None}",
     "    result = {'route': decision, 'timing': timing}"),
])
edit("api/routes_ask.py", [
    ('            evidence_status=getattr(response, "evidence_status", None),\n', ""),
    ('            resolved_concept=getattr(response, "resolved_concept", None),\n', ""),
    ('            investigation_plan=getattr(response, "investigation_plan", None),\n', ""),
])
edit("api/schemas.py", [
    ("    evidence_status: Optional[str] = None\n", ""),
    ("    resolved_concept: Optional[dict] = None\n", ""),
    ("    investigation_plan: Optional[dict] = None\n", ""),
])
edit("tests/test_out_of_scope_gate.py", [('    assert result["investigation_plan"] is None\n', "")])

edit("odoo_addons/miro_ai/controllers/main.py", [
    ("METADATA_FIELDS = (\n    'route', 'confidence', 'evidence_status', 'resolved_concept', 'omitted_for_authorization', 'investigation_plan',\n)",
     "METADATA_FIELDS = ('route', 'confidence', 'omitted_for_authorization')"),
    ("        'evidence_status': data.get('evidence_status'),\n        'resolved_concept': data.get('resolved_concept'),\n", ""),
    ("        'investigation_plan': data.get('investigation_plan'),\n", ""),
])
edit("odoo_addons/miro_ai/models/miro_ai_log.py", [
    ("                'evidence_status': metadata.get('evidence_status'),\n                'investigation_plan': metadata.get('investigation_plan'),\n", ""),
])
edit("odoo_addons/miro_ai/static/src/js/miro_ai.js", [
    ("        evidence_status: null,\n        omitted_for_authorization: [],\n        investigation_plan: null,\n",
     "        omitted_for_authorization: [],\n"),
    ("            evidence_status: turn.evidence_status || null,\n            omitted_for_authorization: turn.omitted_for_authorization || [],\n            investigation_plan: turn.investigation_plan || null,\n",
     "            omitted_for_authorization: turn.omitted_for_authorization || [],\n"),
    ("                    evidence_status: response.evidence_status || null,\n                    omitted_for_authorization: response.omitted_for_authorization || [],\n                    investigation_plan: response.investigation_plan || null,\n",
     "                    omitted_for_authorization: response.omitted_for_authorization || [],\n"),
    ('                    confidence: 0.0,\n                    evidence_status: "ERROR",\n', "                    confidence: 0.0,\n"),
])
xml = "odoo_addons/miro_ai/static/src/xml/miro_ai_assistant.xml"
edit(xml, [("(msg.investigation_plan or (msg.sources and msg.sources.length > 0))", "msg.sources and msg.sources.length > 0")])
cut(xml, '                                        <t t-if="msg.investigation_plan and msg.investigation_plan.steps',
    '                                        <t t-if="msg.sources and msg.sources.length > 0">\n                                            <div class="text-success')

edit("scripts/report_llm_call_budget.py", [
    ('"Lancer `scripts/run_adversarial_benchmark.py` ou interroger le pipeline via "\n            "`rag.graph.query_graph()` pour peupler',
     '"Interroger le pipeline via `core.graph.graph.query_graph()` pour peupler'),
])
