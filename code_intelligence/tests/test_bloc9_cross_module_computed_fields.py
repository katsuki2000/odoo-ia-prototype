"""
code_intelligence/tests/test_bloc9_cross_module_computed_fields.py

, second item: "champs calcules cross-module" was the one gap of
the plan's 4 named pistes NOT already covered by the existing 9-10
adversarial modules (verified by reading every models/*.py in the corpus
-- custom_deep_inheritance_security covers deep inheritance, nested
domain_force, and manual has_group(), but its computed field
(_compute_risk_score) depends only on a field in its OWN module).

New corpus, 3 modules extending hr.expense (untouched by the rest of the
corpus) in a dependency chain:
    custom_expense_risk_base       (raw fields: justificatif_manquant,
                                     nombre_relances)
      -> custom_expense_risk_score (risk_score, compute depends on the
                                     base module's fields + core
                                     hr_expense's total_amount)
        -> custom_expense_risk_alert (alerte_conformite, compute depends
                                       on risk_score -- a field computed
                                       in a DIFFERENT, non-adjacent module
                                       -- AND on a dotted-path field
                                       'employee_id.department_id')

Since Field/Method graph nodes are keyed by (model, name) only, never by
module (see graph_builder.py), single-hop cross-module dependency
resolution turns out to already work with NO code change needed -- this
suite exists to confirm that with a real, non-mocked example.

The two limitations previously documented (single-hop propagation and
trigger_path not surfaced) have been FIXED:
  1. field_change_impact() now walks multi-hop BFS propagation -- a
     2-hop cascade (justificatif_manquant -> risk_score -> alerte_conformite)
     IS fully surfaced by a single call.
  2. A dotted @api.depends path ('employee_id.department_id') is now
     surfaced via upstream_trigger_paths and in the summary_text.
"""

from pathlib import Path

import pytest

from code_intelligence.cross_file_resolver import ParsedModule, build_module_symbol_registry
from code_intelligence.deterministic_tools import field_change_impact
from code_intelligence.graph_builder import OdooGraphBuilder
from code_intelligence.manifest_parser import parse_manifest
from code_intelligence.python_extractor import extract_odoo_models_from_file
from code_intelligence.tests._corpus_paths import CUSTOM_ADDONS_PATH


ADDONS_PATH = CUSTOM_ADDONS_PATH
REAL_MODULES = [
    "custom_expense_risk_base",
    "custom_expense_risk_score",
    "custom_expense_risk_alert",
]


def _build_real_registry_and_graph():
    modules_dict = {}
    for mod_name in REAL_MODULES:
        mod_dir = ADDONS_PATH / mod_name
        manifest = parse_manifest(mod_dir / "__manifest__.py")
        if manifest is None:
            pytest.skip(f"Real module {mod_name} not found at {mod_dir} -- skipping live corpus test.")
        models = []
        for py_file in (mod_dir / "models").glob("*.py"):
            models.extend(extract_odoo_models_from_file(py_file))
        modules_dict[mod_name] = ParsedModule(manifest=manifest, models=models)

    registry = build_module_symbol_registry(modules_dict)
    builder = OdooGraphBuilder(registry, modules_dict)
    G = builder.build_graph()
    return G


def test_manifests_form_the_intended_dependency_chain():
    for mod_name in REAL_MODULES:
        manifest = parse_manifest(ADDONS_PATH / mod_name / "__manifest__.py")
        assert manifest is not None, f"{mod_name} manifest failed to parse"

    base_manifest = parse_manifest(ADDONS_PATH / "custom_expense_risk_base" / "__manifest__.py")
    score_manifest = parse_manifest(ADDONS_PATH / "custom_expense_risk_score" / "__manifest__.py")
    alert_manifest = parse_manifest(ADDONS_PATH / "custom_expense_risk_alert" / "__manifest__.py")

    assert "hr_expense" in base_manifest.depends
    assert "custom_expense_risk_base" in score_manifest.depends
    assert "custom_expense_risk_score" in alert_manifest.depends


def test_extraction_finds_the_right_fields_in_each_module():
    base_models = extract_odoo_models_from_file(
        ADDONS_PATH / "custom_expense_risk_base" / "models" / "hr_expense.py"
    )
    score_models = extract_odoo_models_from_file(
        ADDONS_PATH / "custom_expense_risk_score" / "models" / "hr_expense.py"
    )
    alert_models = extract_odoo_models_from_file(
        ADDONS_PATH / "custom_expense_risk_alert" / "models" / "hr_expense.py"
    )

    base_field_names = {f.name for f in base_models[0].fields}
    assert {"justificatif_manquant", "nombre_relances"} <= base_field_names

    score_field = next(f for f in score_models[0].fields if f.name == "risk_score")
    assert score_field.compute == "_compute_risk_score"
    assert score_field.store is True

    alert_field = next(f for f in alert_models[0].fields if f.name == "alerte_conformite")
    assert alert_field.compute == "_compute_alerte_conformite"
    assert alert_field.store is True


def test_single_hop_cross_module_dependency_already_resolves():
    """The direct case: a field declared in one module correctly shows up
    as an upstream/downstream dependency of a compute field declared in a
    DIFFERENT module -- this already works with no code change, because
    Field/Method graph nodes are keyed by (model, name) only, never by
    module."""
    G = _build_real_registry_and_graph()

    # Downstream of a raw base-module field: the score-module's compute
    # field must show up, one hop away.
    result_base_field = field_change_impact(G, "justificatif_manquant", "hr.expense")
    assert "risk_score" in result_base_field.downstream_computed_fields

    # Upstream of the score-module's compute field: both base-module
    # fields, plus the core hr_expense field total_amount.
    result_score_field = field_change_impact(G, "risk_score", "hr.expense")
    assert "justificatif_manquant" in result_score_field.upstream_triggers
    assert "nombre_relances" in result_score_field.upstream_triggers
    assert "total_amount" in result_score_field.upstream_triggers

    # Downstream of risk_score: the alert-module's compute field, one hop
    # away, even though risk_score and alerte_conformite are declared in
    # two modules that are not directly adjacent in dependency terms
    # (alert depends on score, which depends on base -- there's no direct
    # relationship between "which module" beyond the graph being
    # module-agnostic at the field/method level).
    assert "alerte_conformite" in result_score_field.downstream_computed_fields


def test_two_hop_cascade_IS_now_surfaced_by_a_single_call():
    """Verifies the FIX for the first documented limitation: multi-hop BFS
    propagation now surfaces the full transitive downstream chain.
    Changing justificatif_manquant (base module) transitively impacts
    alerte_conformite (alert module, 2 hops away via risk_score) and a
    single call now reports the complete cascade."""
    G = _build_real_registry_and_graph()

    result = field_change_impact(G, "justificatif_manquant", "hr.expense")
    assert "risk_score" in result.downstream_computed_fields
    # THIS IS THE FIX: alerte_conformite is now found via multi-hop BFS
    assert "alerte_conformite" in result.downstream_computed_fields
    # Propagation depth must be >= 2 (justificatif_manquant -> risk_score -> alerte_conformite)
    assert result.propagation_depth >= 2


def test_dotted_path_dependency_is_now_surfaced():
    """Verifies the FIX for the second documented limitation: the full dotted
    @api.depends path ('employee_id.department_id') is now surfaced in
    upstream_trigger_paths and in the summary_text."""
    G = _build_real_registry_and_graph()

    # The trigger_path edge attribute is still preserved on the graph
    method_node = "method:hr.expense._compute_alerte_conformite"
    assert method_node in G

    depends_edges = {
        v: data.get("trigger_path")
        for _u, v, data in G.out_edges(method_node, data=True)
        if data.get("edge_type") == "DEPENDS_ON"
    }
    assert depends_edges.get("field:hr.expense.employee_id") == "employee_id.department_id"

    # NOW: field_change_impact surfaces the trigger_path in upstream_trigger_paths
    result_alerte = field_change_impact(G, "alerte_conformite", "hr.expense")
    assert "employee_id" in result_alerte.upstream_triggers
    assert result_alerte.upstream_trigger_paths.get("employee_id") == "employee_id.department_id"
    # The full dotted path is now visible in summary_text
    assert "employee_id.department_id" in result_alerte.summary_text

    # And confirm downstream of employee_id now includes alerte_conformite
    result_employee = field_change_impact(G, "employee_id", "hr.expense")
    assert "alerte_conformite" in result_employee.downstream_computed_fields
