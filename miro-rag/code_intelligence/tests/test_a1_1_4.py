"""
code_intelligence/tests/test_a1_1_4.py

Unit tests for Task A1.1.4: Extraction des champs relationnels et attributs.
Tests:
  1. Many2one (comodel_name, string)
  2. One2many (comodel_name, inverse_name)
  3. Many2many (comodel_name, relation_table, column1, column2)
  4. Related fields (related='company_id.code')
  5. Compute fields & store boolean calculation
  6. Real corpus test (sale_order.py)
"""

import tempfile
from pathlib import Path

from code_intelligence.python_extractor import extract_odoo_models_from_file


def test_relational_fields_extraction():
    """Test extraction of Many2one, One2many, Many2many, related, compute, store."""
    code = """
from odoo import models, fields

class SaleOrder(models.Model):
    _name = 'sale.order'

    partner_id = fields.Many2one('res.partner', string='Customer')

    order_line = fields.One2many(
        comodel_name='sale.order.line',
        inverse_name='order_id',
        string='Order Lines'
    )

    tag_ids = fields.Many2many(
        comodel_name='crm.tag',
        relation='sale_order_tag_rel',
        column1='order_id',
        column2='tag_id',
        string='Tags'
    )

    amount_untaxed = fields.Monetary(
        string='Untaxed Amount',
        compute='_compute_amounts',
        store=True
    )

    amount_total = fields.Monetary(
        string='Total',
        compute='_compute_amounts'
    )

    country_code = fields.Char(
        related='partner_id.country_id.code',
        string='Country Code'
    )
"""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(code)
        f_path = Path(f.name)

    try:
        models_found = extract_odoo_models_from_file(f_path)
        assert len(models_found) == 1
        model = models_found[0]
        fields_map = {f.name: f for f in model.fields}

        # 1. Many2one
        assert "partner_id" in fields_map
        p_field = fields_map["partner_id"]
        assert p_field.field_type == "Many2one"
        assert p_field.comodel_name == "res.partner"
        assert p_field.string == "Customer"
        assert p_field.store is True

        # 2. One2many
        assert "order_line" in fields_map
        o_field = fields_map["order_line"]
        assert o_field.field_type == "One2many"
        assert o_field.comodel_name == "sale.order.line"
        assert o_field.inverse_name == "order_id"
        assert o_field.string == "Order Lines"

        # 3. Many2many
        assert "tag_ids" in fields_map
        t_field = fields_map["tag_ids"]
        assert t_field.field_type == "Many2many"
        assert t_field.comodel_name == "crm.tag"
        assert t_field.relation_table == "sale_order_tag_rel"
        assert t_field.column1 == "order_id"
        assert t_field.column2 == "tag_id"

        # 4. Computed field (explicit store=True)
        assert "amount_untaxed" in fields_map
        u_field = fields_map["amount_untaxed"]
        assert u_field.compute == "_compute_amounts"
        assert u_field.store is True

        # 5. Computed field (default store=False)
        assert "amount_total" in fields_map
        tot_field = fields_map["amount_total"]
        assert tot_field.compute == "_compute_amounts"
        assert tot_field.store is False

        # 6. Related field
        assert "country_code" in fields_map
        c_field = fields_map["country_code"]
        assert c_field.related == "partner_id.country_id.code"

    finally:
        f_path.unlink()


def test_real_corpus_sale_order_fields():
    """Test field extraction on real sale_order.py corpus file."""
    corpus_root = Path("/home/user/odoo-17.0/addons")
    sale_order_file = corpus_root / "sale" / "models" / "sale_order.py"

    if sale_order_file.exists():
        models_found = extract_odoo_models_from_file(sale_order_file)
        sale_order = next((m for m in models_found if m.name == "sale.order"), None)
        assert sale_order is not None

        fields_map = {f.name: f for f in sale_order.fields}

        # Check partner_id Many2one
        assert "partner_id" in fields_map
        assert fields_map["partner_id"].comodel_name == "res.partner"

        # Check order_line One2many
        assert "order_line" in fields_map
        assert fields_map["order_line"].comodel_name == "sale.order.line"
        assert fields_map["order_line"].inverse_name == "order_id"
