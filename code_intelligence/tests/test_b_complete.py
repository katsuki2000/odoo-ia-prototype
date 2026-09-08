"""
code_intelligence/tests/test_b_complete.py

Unit tests for B.1.4, B.1.5, B.1.6, , and .
Tests:
  1. B.1.4 trace_full_inheritance (_inherit vs _inherits distinction)
  2. B.1.5 describe_workflow (WorkflowState -> TRANSITIONS_VIA)
  3. B.1.6 3-Level Error Management (FOUND, EMPTY, NOT_FOUND)
  4.  Auxiliary Tools (role resolution, module listing, path explanation, 200-line reader limit)
  5.  Live Comparator & Divergence Detector (TTL cache, non-boolean divergence report)
"""

import tempfile
from pathlib import Path
import pytest
import networkx as nx

from code_intelligence.deterministic_tools import (
    QueryStatus,
    trace_full_inheritance,
    describe_workflow,
    who_has_access_to,
    field_change_impact,
    button_execution_path,
)
from code_intelligence.auxiliary_tools import (
    resolve_technical_name_to_role,
    list_involved_modules,
    explain_decision_path,
    read_precise_source_code,
)
from code_intelligence.live_comparator import (
    clear_live_cache,
    fetch_live_model_security,
    compare_static_vs_live_rules,
)
from code_intelligence.cross_file_resolver import ResolvedSymbolRegistry
from code_intelligence.extractor.xml_extractor import OdooRuleRecord


def test_b1_4_suivre_heritage_complet():
    """Test B.1.4: Full inheritance chain distinguishing _inherit vs _inherits delegation."""
    G = nx.DiGraph()
    G.add_node("model:sale.order", node_type="Model", name="sale.order")
    G.add_node("model:utm.mixin", node_type="Model", name="utm.mixin")
    G.add_node("model:res.partner", node_type="Model", name="res.partner")

    # EXTENDS (_inherit) and DELEGATES_TO (_inherits)
    G.add_edge("model:sale.order", "model:utm.mixin", edge_type="EXTENDS")
    G.add_edge("model:sale.order", "model:res.partner", edge_type="DELEGATES_TO", fk_field="partner_id")

    res = trace_full_inheritance(G, "sale.order")
    assert res.status == QueryStatus.FOUND
    assert "utm.mixin" in res.extension_parents
    assert "res.partner" in res.delegation_parents
    assert res.delegation_parents["res.partner"] == "partner_id"


def test_b1_5_quel_est_le_processus_de():
    """Test B.1.5: Workflow process traversal across WorkflowState nodes."""
    G = nx.DiGraph()
    G.add_node("model:hr.leave", node_type="Model", name="hr.leave")
    G.add_node("state:hr.leave.draft", node_type="WorkflowState", model="hr.leave", state_value="draft")
    G.add_node("state:hr.leave.confirm", node_type="WorkflowState", model="hr.leave", state_value="confirm")

    G.add_edge(
        "state:hr.leave.draft",
        "state:hr.leave.confirm",
        edge_type="TRANSITIONS_VIA",
        method_name="action_confirm",
        label_bouton="Submit",
        groupe_requis=["hr.group_hr_user"]
    )

    res = describe_workflow(G, "hr.leave")
    assert res.status == QueryStatus.FOUND
    assert len(res.transitions) == 1
    assert res.transitions[0]["button_label"] == "Submit"


def test_b1_6_3_level_error_management():
    """Test B.1.6: 3-Level Error Management (FOUND, EMPTY, NOT_FOUND) across tools."""
    G = nx.DiGraph()
    G.add_node("model:sale.order", node_type="Model", name="sale.order")

    # 1. NOT_FOUND case (typo / non-existent model)
    res_nf = trace_full_inheritance(G, "nonexistent.model")
    assert res_nf.status == QueryStatus.NOT_FOUND
    assert "probable typo" in res_nf.summary_text.lower()

    # 2. EMPTY case (model exists, no inheritance)
    res_emp = trace_full_inheritance(G, "sale.order")
    assert res_emp.status == QueryStatus.EMPTY
    assert "does not inherit" in res_emp.summary_text.lower()

    # 3. FOUND case
    G.add_node("model:base", node_type="Model", name="base")
    G.add_edge("model:sale.order", "model:base", edge_type="EXTENDS")
    res_f = trace_full_inheritance(G, "sale.order")
    assert res_f.status == QueryStatus.FOUND


def test_b2_auxiliary_tools():
    """Test : Role resolution, module listing, path explanation, line limit safeguard."""
    # B.2.1 Role resolution
    assert resolve_technical_name_to_role("sales_team.group_sale_manager") == "Responsable Ventes"

    # B.2.2 Module listing
    G = nx.DiGraph()
    G.add_node("model:sale.order", node_type="Model", name="sale.order")
    G.add_node("module:sale", node_type="Module", name="sale")
    G.add_edge("model:sale.order", "module:sale", edge_type="DEFINED_IN")
    assert list_involved_modules(G, "sale.order") == ["sale"]

    # B.2.3 Path explanation
    path_nodes = ["model:sale.order", "module:sale"]
    exp = explain_decision_path(G, path_nodes)
    assert "Step 1:" in exp

    # B.2.4 Source reader safeguard (> 200 lines refused)
    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        f.write("\n".join([f"line {i}" for i in range(300)]))
        f_path = Path(f.name)

    try:
        err_res = read_precise_source_code(str(f_path), 1, 250)
        assert "exceeds maximum safeguard limit" in err_res

        valid_res = read_precise_source_code(str(f_path), 10, 20)
        assert "10 | line 9" in valid_res
    finally:
        f_path.unlink()


def test_a4_1_live_comparator_and_cache():
    """Test : TTL cache and detailed non-boolean divergence report."""
    clear_live_cache()

    # TTL Cache test
    d1 = fetch_live_model_security("sale.order")
    d2 = fetch_live_model_security("sale.order")
    assert d1 is d2 # Cache hit

    clear_live_cache()

    # Divergence test
    registry = ResolvedSymbolRegistry()
    registry.rules["sale.rule1"] = OdooRuleRecord(
        xml_id="sale.rule1",
        filepath="sale/security.xml",
        lineno=1,
        name="Sale Rule 1",
        model_id="model_sale_order",
        domain_force="[('user_id','=',user.id)]"
    )

    live_data = {
        "rules": [
            {
                "name": "Sale Rule 1",
                "domain_force": "[('company_id','=',1)]", # DOMAIN_MODIFIED
                "active": True
            },
            {
                "name": "Sale Rule 2 Live Only", # GROUP_ADDED_IN_LIVE
                "domain_force": "[('state','=','sale')]",
                "active": False # RULE_DISABLED_IN_LIVE
            }
        ]
    }

    result = compare_static_vs_live_rules(registry, "sale.order", live_data)
    assert result.has_divergence is True
    assert len(result.divergences) == 3

    div_types = {d.divergence_type for d in result.divergences}
    assert "DOMAIN_MODIFIED" in div_types
    assert "RULE_DISABLED_IN_LIVE" in div_types
    assert "GROUP_ADDED_IN_LIVE" in div_types
