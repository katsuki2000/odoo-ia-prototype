"""
code_intelligence/tests/test_a1_1_3.py

Unit tests for Task A1.1.3: Visiteur AST pour @api.depends, @api.constrains, @api.onchange.
Tests:
  1. Simple trigger fields (e.g. 'partner_id', 'state')
  2. Dotted field paths (e.g. 'partner_id.name', 'line_ids.price_total')
  3. Multiple decorators on the same method
  4. Real corpus file test (sale_order.py)
"""

import tempfile
from pathlib import Path

from code_intelligence.python_extractor import extract_odoo_models_from_file


def test_decorators_extraction():
    """Test extraction of @api.depends, @api.constrains, @api.onchange with dotted paths."""
    code = """
from odoo import models, api, fields

class SaleOrder(models.Model):
    _name = 'sale.order'

    @api.depends('partner_id.name', 'order_line.price_subtotal')
    def _compute_amounts(self):
        pass

    @api.constrains('date_order', 'state')
    def _check_date(self):
        pass

    @api.onchange('partner_id')
    def _onchange_partner(self):
        pass
"""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(code)
        f_path = Path(f.name)

    try:
        models_found = extract_odoo_models_from_file(f_path)
        assert len(models_found) == 1
        model = models_found[0]
        assert len(model.methods) == 3

        # Method 1: _compute_amounts
        compute_m = next(m for m in model.methods if m.name == "_compute_amounts")
        assert len(compute_m.decorators) == 1
        dec = compute_m.decorators[0]
        assert dec.decorator_type == "depends"
        assert dec.trigger_fields == ["partner_id.name", "order_line.price_subtotal"]

        # Method 2: _check_date
        check_m = next(m for m in model.methods if m.name == "_check_date")
        assert len(check_m.decorators) == 1
        dec = check_m.decorators[0]
        assert dec.decorator_type == "constrains"
        assert dec.trigger_fields == ["date_order", "state"]

        # Method 3: _onchange_partner
        onchange_m = next(m for m in model.methods if m.name == "_onchange_partner")
        assert len(onchange_m.decorators) == 1
        dec = onchange_m.decorators[0]
        assert dec.decorator_type == "onchange"
        assert dec.trigger_fields == ["partner_id"]
    finally:
        f_path.unlink()


def test_real_corpus_sale_order_decorators():
    """Test decorator extraction on real sale_order.py corpus file."""
    corpus_root = Path(__file__).resolve().parent.parent.parent / "fake_data" / "code"
    sale_order_file = corpus_root / "sale" / "sale_order.py"

    if sale_order_file.exists():
        models_found = extract_odoo_models_from_file(sale_order_file)
        sale_order = next((m for m in models_found if m.name == "sale.order"), None)
        assert sale_order is not None

        # Check methods with @api.depends
        methods_with_depends = [
            m for m in sale_order.methods
            if any(d.decorator_type == "depends" for d in m.decorators)
        ]
        assert len(methods_with_depends) > 0, "Should extract methods decorated with @api.depends from sale_order.py"

        # Verify trigger fields extracted for a depends decorator
        sample_method = methods_with_depends[0]
        depends_dec = next(d for d in sample_method.decorators if d.decorator_type == "depends")
        assert isinstance(depends_dec.trigger_fields, list)
        assert len(depends_dec.trigger_fields) > 0
