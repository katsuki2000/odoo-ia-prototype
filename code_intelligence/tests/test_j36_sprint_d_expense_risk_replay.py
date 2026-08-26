"""
code_intelligence/tests/test_j36_sprint_d_expense_risk_replay.py

J36 —  élargi sur le corpus custom_expense_risk_* :
Rejoue les questions de gouvernance du benchmark adversarial directement
sur les outils déterministes (pas de LLM) pour valider que l'agent
Code Intelligence produit les bonnes réponses structurelles sur les
3 modules custom_expense_risk_{base,score,alert}.

Couvre :
  - Cascade multi-hop (justificatif_manquant → risk_score → alerte_conformite)
  - Trigger path dotted (@api.depends('employee_id.department_id'))
  - Upstream cross-module (total_amount core → risk_score custom)
  - Module mapping (3 modules étendent hr.expense)
  - Trick question (champ inexistant)
"""

import json
from pathlib import Path

import pytest

from code_intelligence.cross_file_resolver import ParsedModule, build_module_symbol_registry
from code_intelligence.deterministic_tools import (
    field_change_impact,
    NOT_FOUND_MARKER,
)
from code_intelligence.graph_builder import OdooGraphBuilder
from code_intelligence.manifest_parser import parse_manifest
from code_intelligence.python_extractor import extract_odoo_models_from_file


ADDONS_PATH = Path("/home/user/odoo-17.0/addons")
DATASET_PATH = Path(__file__).resolve().parent.parent / "evaluation" / "test_dataset_expense_risk.json"

EXPENSE_MODULES = [
    "custom_expense_risk_base",
    "custom_expense_risk_score",
    "custom_expense_risk_alert",
]


@pytest.fixture(scope="module")
def expense_graph():
    """Build graph from the 3 custom_expense_risk_* modules."""
    modules_dict = {}
    for mod_name in EXPENSE_MODULES:
        mod_dir = ADDONS_PATH / mod_name
        manifest = parse_manifest(mod_dir / "__manifest__.py")
        if manifest is None:
            pytest.skip(f"Module {mod_name} not found at {mod_dir}")
        models = []
        for py_file in (mod_dir / "models").glob("*.py"):
            models.extend(extract_odoo_models_from_file(py_file))
        modules_dict[mod_name] = ParsedModule(manifest=manifest, models=models)

    registry = build_module_symbol_registry(modules_dict)
    builder = OdooGraphBuilder(registry, modules_dict)
    G = builder.build_graph()
    return G, modules_dict


@pytest.fixture(scope="module")
def dataset():
    """Load the J36 benchmark dataset."""
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# EXP_01: justificatif_manquant → {risk_score, alerte_conformite} (2-hop)
# ---------------------------------------------------------------------------
def test_exp_01_justificatif_manquant_cascade(expense_graph):
    G, _ = expense_graph
    result = field_change_impact(G, "justificatif_manquant", "hr.expense")
    assert "risk_score" in result.downstream_computed_fields
    assert "alerte_conformite" in result.downstream_computed_fields
    assert result.propagation_depth >= 2


# ---------------------------------------------------------------------------
# EXP_02: nombre_relances → {risk_score, alerte_conformite} (2-hop)
# ---------------------------------------------------------------------------
def test_exp_02_nombre_relances_cascade(expense_graph):
    G, _ = expense_graph
    result = field_change_impact(G, "nombre_relances", "hr.expense")
    assert "risk_score" in result.downstream_computed_fields
    assert "alerte_conformite" in result.downstream_computed_fields
    assert result.propagation_depth >= 2


# ---------------------------------------------------------------------------
# EXP_03: risk_score upstream = {justificatif_manquant, nombre_relances, total_amount}
#          risk_score downstream = {alerte_conformite}
# ---------------------------------------------------------------------------
def test_exp_03_risk_score_upstream_and_downstream(expense_graph):
    G, _ = expense_graph
    result = field_change_impact(G, "risk_score", "hr.expense")
    # Upstream: 3 fields from 2 different modules
    assert "justificatif_manquant" in result.upstream_triggers
    assert "nombre_relances" in result.upstream_triggers
    assert "total_amount" in result.upstream_triggers
    # Downstream: 1-hop to alerte_conformite
    assert "alerte_conformite" in result.downstream_computed_fields


# ---------------------------------------------------------------------------
# EXP_04: alerte_conformite upstream = {employee_id, risk_score}
#          with trigger_path employee_id → employee_id.department_id
# ---------------------------------------------------------------------------
def test_exp_04_alerte_conformite_upstream_with_trigger_path(expense_graph):
    G, _ = expense_graph
    result = field_change_impact(G, "alerte_conformite", "hr.expense")
    assert "employee_id" in result.upstream_triggers
    assert "risk_score" in result.upstream_triggers
    # Dotted trigger path is surfaced
    assert result.upstream_trigger_paths.get("employee_id") == "employee_id.department_id"
    # The summary must mention the full dotted path
    assert "employee_id.department_id" in result.summary_text


# ---------------------------------------------------------------------------
# EXP_05: employee_id downstream contains alerte_conformite
# ---------------------------------------------------------------------------
def test_exp_05_employee_id_downstream(expense_graph):
    G, _ = expense_graph
    result = field_change_impact(G, "employee_id", "hr.expense")
    assert "alerte_conformite" in result.downstream_computed_fields


# ---------------------------------------------------------------------------
# EXP_06: Module mapping — all 3 modules extend hr.expense
# ---------------------------------------------------------------------------
def test_exp_06_module_mapping(expense_graph):
    G, modules_dict = expense_graph
    # Verify all 3 modules are in the graph's module list
    for mod_name in EXPENSE_MODULES:
        assert mod_name in modules_dict
    # Verify the graph has the hr.expense model node
    assert "model:hr.expense" in G


# ---------------------------------------------------------------------------
# EXP_07: total_amount (core) → risk_score (custom cross-module)
# ---------------------------------------------------------------------------
def test_exp_07_total_amount_cross_module(expense_graph):
    G, _ = expense_graph
    result = field_change_impact(G, "total_amount", "hr.expense")
    assert "risk_score" in result.downstream_computed_fields


# ---------------------------------------------------------------------------
# EXP_08: Trick — non-existent field returns NOT_FOUND
# ---------------------------------------------------------------------------
def test_exp_08_trick_nonexistent_field(expense_graph):
    G, _ = expense_graph
    result = field_change_impact(G, "champ_inexistant_xyz", "hr.expense")
    assert NOT_FOUND_MARKER in result.summary_text
    assert result.downstream_computed_fields == []
    assert result.upstream_triggers == []
