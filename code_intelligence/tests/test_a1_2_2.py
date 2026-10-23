from code_intelligence.tests._corpus_paths import CUSTOM_ADDONS_PATH
"""
code_intelligence/tests/test_a1_2_2.py

Unit tests for Task A1.2.2: Parser res.groups & ir.actions.act_window.
Tests:
  1. res.groups parsing with implied_ids hierarchy and category_id
  2. ir.actions.act_window parsing with restrictive groups_id
  3. Real XML test on odoo17-dev/addons/miro_ai/security/miro_ai_security.xml
"""

import tempfile
from pathlib import Path

from code_intelligence.extractor.xml import parse_groups_from_xml, parse_actions_from_xml


def test_groups_and_actions_extraction():
    """Test extraction of res.groups implied_ids hierarchy and act_window groups_id."""
    xml_content = """<odoo>
    <data>
        <record id="group_sales_user" model="res.groups">
            <field name="name">Sales User</field>
            <field name="category_id" ref="base.module_category_sales"/>
        </record>

        <record id="group_sales_manager" model="res.groups">
            <field name="name">Sales Manager</field>
            <field name="category_id" ref="base.module_category_sales"/>
            <field name="implied_ids" eval="[(4, ref('group_sales_user'))]"/>
        </record>

        <record id="action_restricted_orders" model="ir.actions.act_window">
            <field name="name">Manager Sales Orders</field>
            <field name="res_model">sale.order</field>
            <field name="view_mode">tree,form</field>
            <field name="groups_id" eval="[(4, ref('group_sales_manager'))]"/>
        </record>
    </data>
</odoo>
"""
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as f:
        f.write(xml_content)
        f_path = Path(f.name)

    try:
        # 1. Test groups
        groups = parse_groups_from_xml(f_path)
        assert len(groups) == 2
        groups_map = {g.xml_id: g for g in groups}

        assert "group_sales_user" in groups_map
        user_grp = groups_map["group_sales_user"]
        assert user_grp.name == "Sales User"
        assert user_grp.category_id == "base.module_category_sales"
        assert user_grp.implied_ids == []

        assert "group_sales_manager" in groups_map
        mgr_grp = groups_map["group_sales_manager"]
        assert mgr_grp.name == "Sales Manager"
        assert mgr_grp.category_id == "base.module_category_sales"
        assert mgr_grp.implied_ids == ["group_sales_user"]

        # 2. Test window action
        actions = parse_actions_from_xml(f_path)
        assert len(actions) == 1
        action = actions[0]

        assert action.xml_id == "action_restricted_orders"
        assert action.name == "Manager Sales Orders"
        assert action.res_model == "sale.order"
        assert action.view_mode == "tree,form"
        assert action.groups_id == ["group_sales_manager"]

    finally:
        f_path.unlink()


def test_real_xml_miro_ai_groups():
    """Test parsing res.groups from real miro_ai_security.xml."""
    root_dir = Path(__file__).resolve().parent.parent.parent.parent
    xml_file = CUSTOM_ADDONS_PATH / "miro_ai" / "security" / "miro_ai_security.xml"

    if xml_file.exists():
        groups = parse_groups_from_xml(xml_file)
        assert len(groups) >= 2

        groups_map = {g.xml_id: g for g in groups}
        assert "group_miro_ai_admin" in groups_map

        admin_group = groups_map["group_miro_ai_admin"]
        assert admin_group.name == "MIRO AI Administrator"
        assert admin_group.category_id == "module_category_miro_ai"
        assert admin_group.implied_ids == ["group_miro_ai_user"]
