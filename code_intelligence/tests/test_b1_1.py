"""
code_intelligence/tests/test_b1_1.py

Unit tests for Tool who_has_access_to(model, permission, group_id=None).
Tests:
  1. Access evaluation for read/write permissions
  2. Group hierarchy expansion (Child group inheriting Parent group via IMPLIES edge)
  3. ir.rule domain_force extraction
  4. Specific group_id query mode
  5. Real graph test on miro_ai module
"""

from pathlib import Path
import pytest
import networkx as nx

from code_intelligence.extractor.manifest_parser import parse_manifest
from code_intelligence.extractor.python_extractor import extract_odoo_models_from_file
from code_intelligence.extractor.xml_extractor import parse_ir_rules_from_xml, parse_groups_from_xml
from code_intelligence.extractor.csv_extractor import parse_access_control_csv
from code_intelligence.cross_file_resolver import ParsedModule, build_module_symbol_registry
from code_intelligence.graph_builder import OdooGraphBuilder
from code_intelligence.deterministic_tools import who_has_access_to


def test_qui_a_acces_a_synthetic():
    """Test who_has_access_to on synthetic graph with ACL, Groups, and Record Rules."""
    G = nx.DiGraph()

    # Nodes
    G.add_node("model:sale.order", node_type="Model", name="sale.order")
    G.add_node("acl:sale.access_user", node_type="AccessEntry", perm_read=True, perm_write=True, perm_create=True, perm_unlink=False, all_authenticated=False)
    G.add_node("group:sales_team.group_sale_salesman", node_type="Group", name="User")
    G.add_node("group:sales_team.group_sale_manager", node_type="Group", name="Manager")
    G.add_node("rule:sale.rule_user", node_type="Rule", name="User Rule", domain_force="[('user_id','=',user.id)]", perm_read=True, perm_write=True)

    # Edges
    G.add_edge("model:sale.order", "acl:sale.access_user", edge_type="GRANTED_BY")
    G.add_edge("acl:sale.access_user", "group:sales_team.group_sale_salesman", edge_type="APPLIES_TO_GROUP")
    G.add_edge("group:sales_team.group_sale_manager", "group:sales_team.group_sale_salesman", edge_type="IMPLIES")
    G.add_edge("model:sale.order", "rule:sale.rule_user", edge_type="RESTRICTED_BY")
    G.add_edge("rule:sale.rule_user", "group:sales_team.group_sale_salesman", edge_type="APPLIES_TO_GROUP")

    # 1. Query read access for model:sale.order
    res_read = who_has_access_to(G, "sale.order", permission="read")
    assert res_read.model_name == "sale.order"
    assert "sales_team.group_sale_salesman" in res_read.allowed_groups
    # Check group hierarchy expansion (Manager inherits User via IMPLIES)
    assert "sales_team.group_sale_manager" in res_read.allowed_groups
    assert len(res_read.active_rules) == 1
    assert res_read.active_rules[0].domain_force == "[('user_id','=',user.id)]"

    # 2. Query unlink access for model:sale.order (perm_unlink is False on ACL)
    res_unlink = who_has_access_to(G, "sale.order", permission="unlink")
    assert len(res_unlink.allowed_groups) == 0

    # 3. Query specific group_id
    res_grp = who_has_access_to(G, "sale.order", permission="write", group_id="sales_team.group_sale_manager")
    assert "HAS WRITE access" in res_grp.summary_text


def test_qui_a_acces_a_real_miro_ai():
    """Test who_has_access_to on real miro_ai module graph."""
    root_dir = Path(__file__).resolve().parent.parent.parent.parent
    mod_dir = Path("/home/user/odoo-17.0/addons") / "miro_ai"

    if mod_dir.exists():
        manifest = parse_manifest(mod_dir / "__manifest__.py")
        mod = ParsedModule(manifest=manifest)
        for py_file in mod_dir.rglob("*.py"):
            mod.models.extend(extract_odoo_models_from_file(py_file))
        for xml_file in mod_dir.rglob("*.xml"):
            mod.rules.extend(parse_ir_rules_from_xml(xml_file))
            mod.groups.extend(parse_groups_from_xml(xml_file))
        for csv_file in mod_dir.rglob("*.csv"):
            mod.acl_entries.extend(parse_access_control_csv(csv_file))

        modules = {"miro_ai": mod}
        registry = build_module_symbol_registry(modules)
        builder = OdooGraphBuilder(registry, modules)
        G = builder.build_graph()

        # Query access for miro.ai.log
        res = who_has_access_to(G, "miro.ai.log", permission="read")
        assert res.model_name == "miro.ai.log"
        assert len(res.allowed_groups) > 0 or res.all_authenticated_access is True
        assert len(res.active_rules) > 0
        assert any("user_id" in r.domain_force for r in res.active_rules)
