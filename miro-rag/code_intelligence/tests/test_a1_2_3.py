"""
code_intelligence/tests/test_a1_2_3.py

Unit tests for Task A1.2.3: Parser ir.model.fields XML & <menuitem>.
Tests:
  1. ir.model.fields XML record extraction
  2. <menuitem> extraction with groups, parent, and action
  3. Real XML test on odoo17-dev/addons/miro_ai/views/miro_ai_menus.xml
"""

import tempfile
from pathlib import Path

from code_intelligence.xml_extractor import (
    parse_xml_fields_from_xml,
    parse_menuitems_from_xml,
)


def test_xml_fields_and_menuitems_extraction():
    """Test extraction of ir.model.fields XML records and <menuitem> elements."""
    xml_content = """<odoo>
    <data>
        <record id="field_custom_reason" model="ir.model.fields">
            <field name="name">x_reason</field>
            <field name="model_id" ref="model_sale_order"/>
            <field name="field_description">Cancellation Reason</field>
            <field name="ttype">char</field>
        </record>

        <menuitem id="menu_sale_root" name="Sales" sequence="10"/>
        <menuitem id="menu_sale_order" name="Orders" parent="menu_sale_root" action="action_orders" groups="sales_team.group_sale_salesman"/>
    </data>
</odoo>
"""
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as f:
        f.write(xml_content)
        f_path = Path(f.name)

    try:
        # 1. Test ir.model.fields
        fields_list = parse_xml_fields_from_xml(f_path)
        assert len(fields_list) == 1
        f_rec = fields_list[0]
        assert f_rec.xml_id == "field_custom_reason"
        assert f_rec.name == "x_reason"
        assert f_rec.model == "model_sale_order"
        assert f_rec.field_description == "Cancellation Reason"
        assert f_rec.ttype == "char"

        # 2. Test menuitems
        menus = parse_menuitems_from_xml(f_path)
        assert len(menus) == 2
        menus_map = {m.xml_id: m for m in menus}

        assert "menu_sale_root" in menus_map
        root_menu = menus_map["menu_sale_root"]
        assert root_menu.name == "Sales"
        assert root_menu.sequence == 10

        assert "menu_sale_order" in menus_map
        order_menu = menus_map["menu_sale_order"]
        assert order_menu.name == "Orders"
        assert order_menu.parent == "menu_sale_root"
        assert order_menu.action == "action_orders"
        assert order_menu.groups == ["sales_team.group_sale_salesman"]

    finally:
        f_path.unlink()


def test_real_xml_miro_ai_menus():
    """Test parsing menuitems from real miro_ai_menus.xml."""
    root_dir = Path(__file__).resolve().parent.parent.parent.parent
    xml_file = Path("/home/user/odoo-17.0/addons") / "miro_ai" / "views" / "miro_ai_menus.xml"

    if xml_file.exists():
        menus = parse_menuitems_from_xml(xml_file)
        assert len(menus) >= 2
        menus_map = {m.xml_id: m for m in menus}
        assert any("menu_miro_ai" in m_id for m_id in menus_map)
