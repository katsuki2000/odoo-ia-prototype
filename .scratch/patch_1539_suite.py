from pathlib import Path


def edit(path, replacements):
    file = Path(path)
    text = file.read_text()
    for old, new in replacements:
        assert text.count(old) == 1, f'{path}: pattern found {text.count(old)} times: {old[:60]!r}'
        text = text.replace(old, new)
    file.write_text(text)


edit('config/settings.py', [
    ("LATENCY_BUDGET_RESOLVER_MS = int(os.getenv('LATENCY_BUDGET_RESOLVER_MS', '2000'))\n", ''),
    ("LATENCY_BUDGET_PER_HOP_MS = int(os.getenv('LATENCY_BUDGET_PER_HOP_MS', '3000'))\n", ''),
    ("LATENCY_BUDGET_SYNTHESIS_MS = int(os.getenv('LATENCY_BUDGET_SYNTHESIS_MS', '4000'))\n", ''),
    ("LATENCY_BUDGET_XMLRPC_MS = int(os.getenv('LATENCY_BUDGET_XMLRPC_MS', '5000'))\n", ''),
    ("ORM_USE_TYPED_RUNTIME = os.getenv('ORM_USE_TYPED_RUNTIME', 'true').lower() in ('true', '1', 'yes')\n", ''),
    ("MAX_MODELS_PER_QUERY = int(os.getenv('MAX_MODELS_PER_QUERY', '3'))\n", ''),
])

edit('code_intelligence/tests/test_j30_31_latency_budget.py', [
    ("    LATENCY_BUDGET_P90_SECONDS,\n    LATENCY_BUDGET_RESOLVER_MS,\n    LATENCY_BUDGET_PER_HOP_MS,\n"
     "    LATENCY_BUDGET_SYNTHESIS_MS,\n    LATENCY_BUDGET_XMLRPC_MS,\n)\n",
     "    LATENCY_BUDGET_P90_SECONDS,\n)\n"),
    ("    \"\"\"J30-J31: verify all required latency budget constants are configured.\"\"\"\n"
     "    assert LATENCY_BUDGET_P90_SECONDS > 0\n"
     "    assert LATENCY_BUDGET_RESOLVER_MS > 0\n    assert LATENCY_BUDGET_PER_HOP_MS > 0\n"
     "    assert LATENCY_BUDGET_SYNTHESIS_MS > 0\n    assert LATENCY_BUDGET_XMLRPC_MS > 0\n",
     "    \"\"\"J30-J31: verify the latency budget constant is configured.\"\"\"\n"
     "    assert LATENCY_BUDGET_P90_SECONDS > 0\n"),
])

edit('code_intelligence/tests/test_j32_33_massive_extraction_guard.py', [
    ("5. Verifies MAX_MODELS_PER_QUERY limits resolved models to 3 max.\n6. Verifies tools reject",
     "5. Verifies tools reject"),
    ("from config.settings import (\n    MAX_MODELS_PER_QUERY,\n    MASSIVE_EXTRACTION_REFUSAL_MSG,",
     "from config.settings import (\n    MASSIVE_EXTRACTION_REFUSAL_MSG,"),
    ("\n\ndef test_max_models_per_query_limit_constant():\n"
     "    \"\"\"J32-J33: verify MAX_MODELS_PER_QUERY is set to 3.\"\"\"\n"
     "    assert MAX_MODELS_PER_QUERY == 3\n", "\n"),
])

edit('erp_data/tests/test_p9_typed_runtime_wiring.py', [
    ("def test_resolve_orm_tools_exposes_only_generic_read_primitives(monkeypatch):\n"
     "    monkeypatch.setattr(\"config.settings.ORM_USE_TYPED_RUNTIME\", False, raising=False)\n",
     "def test_resolve_orm_tools_exposes_only_generic_read_primitives():\n"),
])
print('patch OK')
