"""
code_intelligence/tests/test_a1_2_4.py

Unit tests for Task A1.2.4: Parser vues formulaire (arch de ir.ui.view, labels de boutons de transition).
Tests:
  1. ir.ui.view form button extraction (name="action_confirm", string="Confirmer")
  2. Button groups and states attributes extraction
  3. Real XML test on fake_data/code/sale/sale_order_view.xml
"""

import tempfile
from pathlib import Path

from code_intelligence.xml_extractor import parse_views_from_xml


def test_form_view_buttons_extraction():
    """Test extraction of ir.ui.view form buttons with name, string, states, and groups."""
    xml_content = """<odoo>
    <data>
        <record id="view_sale_order_form_test" model="ir.ui.view">
            <field name="name">sale.order.form</field>
            <field name="model">sale.order</field>
            <field name="arch" type="xml">
                <form string="Sales Order">
                    <header>
                        <button name="action_confirm" string="Confirmer" type="object" states="draft,sent" groups="sales_team.group_sale_salesman"/>
                        <button name="action_cancel" string="Annuler" type="object" states="draft,sent,sale"/>
                    </header>
                </form>
            </field>
        </record>
    </data>
</odoo>
"""
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as f:
        f.write(xml_content)
        f_path = Path(f.name)

    try:
        views = parse_views_from_xml(f_path)
        assert len(views) == 1
        view = views[0]

        assert view.xml_id == "view_sale_order_form_test"
        assert view.name == "sale.order.form"
        assert view.model == "sale.order"
        assert len(view.buttons) == 2

        btn_confirm = view.buttons[0]
        assert btn_confirm.name == "action_confirm"
        assert btn_confirm.string == "Confirmer"
        assert btn_confirm.type == "object"
        assert btn_confirm.states == "draft,sent"
        assert btn_confirm.groups == ["sales_team.group_sale_salesman"]

        btn_cancel = view.buttons[1]
        assert btn_cancel.name == "action_cancel"
        assert btn_cancel.string == "Annuler"
        assert btn_cancel.states == "draft,sent,sale"

    finally:
        f_path.unlink()


def test_real_xml_sale_order_view():
    """Test parsing form views from real sale_order_view.xml corpus file."""
    corpus_root = Path(__file__).resolve().parent.parent.parent / "fake_data" / "code"
    xml_file = corpus_root / "sale" / "sale_order_view.xml"

    if xml_file.exists():
        views = parse_views_from_xml(xml_file)
        assert len(views) >= 1
        view = views[0]
        assert view.model == "sale.order"
        assert len(view.buttons) > 0

        btn_confirm = next((b for b in view.buttons if b.name == "action_confirm"), None)
        assert btn_confirm is not None
        assert btn_confirm.string in {"Confirm", "Confirmer"}
