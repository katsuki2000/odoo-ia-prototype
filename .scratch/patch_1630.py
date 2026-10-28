import re
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


def set_docstring(path, doc):
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    end = text.index('"""', text.index('"""') + 3) + 3
    p.write_text(f'"""{doc}"""' + text[end:], encoding="utf-8")


edit("config/settings.py", [("CI_MAX_HOPS = 15\n", "")])
edit("conftest.py", [(
    "# Modules import the hop budget from config.settings at import time: pin it before any test module is collected.\n"
    "from config import settings as _settings\n\n_settings.CI_MAX_HOPS = 20\n\n\n", "")])

edit("core/session/reasoning_trace_logger.py", [
    ("from config.settings import CI_MAX_HOPS\n\n", "\n"),
    ("hop_cap: int = MAX_HOPS_PER_QUESTION,", "hop_cap: Optional[int] = None,"),
    ("hop_cap_hit=hop_count >= hop_cap,", "hop_cap_hit=hop_cap is not None and hop_count >= hop_cap,"),
    ("hops=%d/%d llm_calls", "hops=%d/%s llm_calls"),
])
cut("core/session/reasoning_trace_logger.py", "# Maximum tool hops per question guardrail", "\n\n@dataclass\nclass ReasoningHop")
edit("core/session/__init__.py", [("    MAX_HOPS_PER_QUESTION,\n", ""), ('    "MAX_HOPS_PER_QUESTION",\n', "")])
edit("scripts/report_llm_call_budget.py", [
    ("import ReasoningTraceLogger, MAX_HOPS_PER_QUESTION", "import ReasoningTraceLogger"),
    ('(0 par construction). "\n        f"Valeur generique de reference : `MAX_HOPS_PER_QUESTION={MAX_HOPS_PER_QUESTION}` "\n        f"(core.session.reasoning_trace_logger).*\\n"',
     '(0 par construction).*\\n"'),
])

cut("core/schemas.py", "    loop_resolved_concept: Optional[dict]", "    investigation_plan: Optional[dict]")
cut("core/schemas.py", "    ci_evidence_sufficiency: Optional[dict]", "    verification: Optional[VerificationReport]")
edit("core/state.py", [("    loop_resolved_concept: Optional[dict]\n", ""), ("    ci_evidence_sufficiency: Optional[dict]\n", "")])
edit("core/graph/graph_nodes.py", [
    ("        response.loop_resolved_concept = state.get('loop_resolved_concept')\n", ""),
    ("        response.ci_evidence_sufficiency = state.get('ci_evidence_sufficiency')\n        response.rag_fallback = False\n", ""),
])
p = Path("core/graph/graph_nodes.py")
text = p.read_text(encoding="utf-8")
i = text.index("\n\ndef ci_evidence_decision(")
p.write_text(text[:i].rstrip("\n") + "\n", encoding="utf-8")
edit("core/graph/__init__.py", [("    ci_evidence_decision,\n", ""), ('    "ci_evidence_decision",\n', "")])
edit("api/routes_ask.py", [('            loop_resolved_concept=getattr(response, "loop_resolved_concept", None),\n', "")])
edit("api/schemas.py", [("    loop_resolved_concept: Optional[dict] = None\n", "")])

edit("tests/test_source_mode_routing.py", [
    ("from core.graph.graph_nodes import ci_evidence_decision\n", ""),
])
cut("tests/test_source_mode_routing.py", "def test_ci_evidence_decision_documentation_goes_to_generate", "def test_ask_request_source_mode_validation")
edit("tests/test_t3_verify_node.py", [('        ci_evidence_sufficiency={"status": "insufficient"},\n', "")])
edit("tests/architecture/test_import_layers.py", [
    ("Engines (code_intelligence, document_rag, erp_data)", "Engines (document_rag, erp_data)"),
    ('ENGINES = ("code_intelligence", "document_rag", "erp_data")', 'ENGINES = ("document_rag", "erp_data")'),
])

set_docstring("tests/__init__.py", "Test package: lets pytest resolve `tests` from the project root.")
set_docstring("core/__init__.py", "core: LangGraph pipeline, routing, schemas, LLM client.")
set_docstring("tests/document_rag/__init__.py", "Tests of document_rag.")
set_docstring("erp_data/tests/__init__.py", "Tests of erp_data.")
set_docstring("tests/test_degenerate_repetition_guard.py",
              "\nUnit tests of the degenerate-repetition detectors and strippers (core.output).\n")

p = Path("core/llm/llm_retry.py")
text = p.read_text(encoding="utf-8")
start = text.index('    """Truncate excessively long messages')
end = text.index('"""', start + 3) + 3
text = text[:start] + '    """Truncate excessively long messages after a provider payload-size error (emergency fallback)."""' + text[end:]
assert text.count("Node [code_intelligence_agent]: emergency") == 1
text = text.replace("Node [code_intelligence_agent]: emergency", "LLM client: emergency")
p.write_text(text, encoding="utf-8")
