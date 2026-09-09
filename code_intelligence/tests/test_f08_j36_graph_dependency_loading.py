from code_intelligence.tests._corpus_paths import CORE_ADDONS_PATH
"""
code_intelligence/tests/test_f08_j36_graph_dependency_loading.py

Regression lock for the 2026-08-07 J36 fix in
rag/graph.py::get_code_intelligence_graph(): custom_* modules that
_inherit a REAL Odoo core module (e.g. custom_expense_risk_base extends
hr.expense via depends=['hr_expense']) must have that direct dependency's
own module loaded too, or the extended model's BASE declaration (and its
real fields) never enters the graph and every tool call against it returns
"model not found" -- confirmed root cause of the J36  replay
failure (0/8, see evaluation/eval_report_j36_expense_risk.md; the pre-fix
graph is preserved as
code_intelligence/active_graph.json.stale_pre_f08_j36_fix_20260807 for
comparison).

Unlike test_j36_sprint_d_expense_risk_replay.py -- which builds its graph
by hand from only the 3 custom_expense_risk_* modules and therefore never
loads hr_expense either, so it could not have caught this gap even though
its name suggests it covers J36 (it predates the fix, 2026-08-06) -- this
file rebuilds the graph through get_code_intelligence_graph() itself, the
exact function production calls. That is what makes it a real regression
lock: it fails again if the direct-dependency-loading block is ever
removed, narrowed, or short-circuited.

Deliberately has NO LLM/Groq dependency (unlike eval_j36_expense_risk_llm.py)
so it can run fast and offline as part of the normal test suite, instead of
being the only thing standing between this regression and a live rerun of
the adversarial benchmark.

Not executed in this session -- no execution access on this machine from
the agent, file read/write only. Run before considering this fix's test
coverage complete:
    pytest code_intelligence/tests/test_f08_j36_graph_dependency_loading.py -v
"""

from pathlib import Path

import pytest

from code_intelligence.deterministic.field_impact import field_change_impact

ADDONS_ROOT = CORE_ADDONS_PATH


@pytest.fixture(scope="module")
def rebuilt_graph():
    """Force a full rebuild of the production graph against a throwaway
    cache path, so this test never reads/writes the real active_graph.json
    and always exercises the CURRENT loading code in get_code_intelligence_graph()
    -- never a stale cached graph that predates a future regression."""
    if not (ADDONS_ROOT / "hr_expense").exists():
        pytest.skip("Real odoo-17.0/addons corpus not available on this machine.")

    import core.graph as graph_module

    original_path = graph_module.GRAPH_JSON_PATH
    original_cache = graph_module._CACHED_CODE_INTEL_GRAPH
    original_mtime = graph_module._CACHED_GRAPH_MTIME

    import tempfile
    with tempfile.TemporaryDirectory() as tmp_dir:
        graph_module.GRAPH_JSON_PATH = Path(tmp_dir) / "test_graph.json"
        graph_module._CACHED_CODE_INTEL_GRAPH = None
        graph_module._CACHED_GRAPH_MTIME = 0.0
        try:
            G = graph_module.get_code_intelligence_graph()
            yield G
        finally:
            graph_module.GRAPH_JSON_PATH = original_path
            graph_module._CACHED_CODE_INTEL_GRAPH = original_cache
            graph_module._CACHED_GRAPH_MTIME = original_mtime


def test_hr_expense_base_model_is_loaded(rebuilt_graph):
    """model:hr.expense must exist in the production graph at all -- before
    the fix it could still appear as a bare placeholder node synthesized
    from the custom modules' _inherit references, so this alone is a weak
    check; the two tests below verify it carries its REAL base content."""
    assert "model:hr.expense" in rebuilt_graph


def test_real_base_field_impact_reaches_custom_cascade(rebuilt_graph):
    """total_amount is declared on the REAL hr_expense module (see
    odoo-17.0/addons/hr_expense/models/hr_expense.py), not on any
    custom_* module. Before the fix hr_expense was never loaded, so this
    field did not exist in the graph at all and this call returned
    NOT_FOUND. It must now show the real cross-module cascade into the
    custom risk-scoring field (this is the EXP_07 case from
    evaluation/test_dataset_expense_risk.json)."""
    result = field_change_impact(rebuilt_graph, "total_amount", "hr.expense")
    assert "risk_score" in result.downstream_computed_fields


def test_employee_id_is_the_real_base_field_not_a_phantom_reference(rebuilt_graph):
    """employee_id is declared on hr.expense itself, in the hr_expense
    module (required=True there) -- not invented by any custom_* module.
    If the base module were still unloaded, this upstream trigger for
    alerte_conformite would not resolve to a real field declaration at
    all (this is the EXP_04/EXP_05 case from
    evaluation/test_dataset_expense_risk.json)."""
    result = field_change_impact(rebuilt_graph, "employee_id", "hr.expense")
    assert "alerte_conformite" in result.downstream_computed_fields
