from code_intelligence.tests._corpus_paths import CORE_ADDONS_PATH
"""
code_intelligence/tests/test_a1_1_2.py

Unit tests for Visiteur AST (_name, _inherit, _inherits distinction).
Tests 3 cases:
  1. Extension (_inherit alone without _name) -> ModelRelationType.EXTENSION
  2. Classic Inheritance (_name + _inherit) -> ModelRelationType.CLASSIC_INHERITANCE
  3. Delegation (_inherits dict) -> ModelRelationType.DELEGATION
"""

import tempfile
from pathlib import Path
import pytest

from code_intelligence.extractor.python_extractor import (
    extract_odoo_models_from_file,
    ModelRelationType,
)


def test_extension_pattern():
    """Case 1: Extension pattern (_inherit alone, modifying existing model)."""
    code = """
from odoo import models, fields

class ResPartner(models.Model):
    _inherit = 'res.partner'

    sale_order_count = fields.Integer(string='Sale Order Count')
"""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(code)
        f_path = Path(f.name)

    try:
        models_found = extract_odoo_models_from_file(f_path)
        assert len(models_found) == 1
        decl = models_found[0]
        assert decl.class_name == "ResPartner"
        assert decl.name is None
        assert decl.inherit == ["res.partner"]
        assert ModelRelationType.EXTENSION in decl.relation_types
        assert ModelRelationType.CLASSIC_INHERITANCE not in decl.relation_types
        assert ModelRelationType.DELEGATION not in decl.relation_types
    finally:
        f_path.unlink()


def test_classic_inheritance_pattern():
    """Case 2: Classic inheritance (_name + _inherit, creating new model)."""
    code = """
from odoo import models, fields

class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherit = ['portal.mixin', 'mail.thread']
    _description = 'Sales Order'

    name = fields.Char(string='Order Reference')
"""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(code)
        f_path = Path(f.name)

    try:
        models_found = extract_odoo_models_from_file(f_path)
        assert len(models_found) == 1
        decl = models_found[0]
        assert decl.class_name == "SaleOrder"
        assert decl.name == "sale.order"
        assert decl.inherit == ["portal.mixin", "mail.thread"]
        assert ModelRelationType.CLASSIC_INHERITANCE in decl.relation_types
        assert ModelRelationType.EXTENSION not in decl.relation_types
        assert ModelRelationType.DELEGATION not in decl.relation_types
    finally:
        f_path.unlink()


def test_delegation_pattern():
    """Case 3: Delegation pattern (_inherits dict)."""
    code = """
from odoo import models, fields

class ProductProduct(models.Model):
    _name = 'product.product'
    _inherits = {'product.template': 'product_tmpl_id'}
    _description = 'Product Variant'

    product_tmpl_id = fields.Many2one('product.template', string='Product Template')
"""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(code)
        f_path = Path(f.name)

    try:
        models_found = extract_odoo_models_from_file(f_path)
        assert len(models_found) == 1
        decl = models_found[0]
        assert decl.class_name == "ProductProduct"
        assert decl.name == "product.product"
        assert decl.inherits == {"product.template": "product_tmpl_id"}
        assert ModelRelationType.DELEGATION in decl.relation_types
        assert ModelRelationType.BASE in decl.relation_types
    finally:
        f_path.unlink()


def test_real_corpus_files():
    """Test on actual corpus files from addons."""
    corpus_root = CORE_ADDONS_PATH
    
    # 1. Extension test on sale/models/res_partner.py
    res_partner_file = corpus_root / "sale" / "models" / "res_partner.py"
    if res_partner_file.exists():
        decls = extract_odoo_models_from_file(res_partner_file)
        assert any(d.class_name == "ResPartner" and d.inherit == ["res.partner"] for d in decls)

    # 2. Classic inheritance test on sale/models/sale_order.py
    sale_order_file = corpus_root / "sale" / "models" / "sale_order.py"
    if sale_order_file.exists():
        decls = extract_odoo_models_from_file(sale_order_file)
        assert any(d.class_name == "SaleOrder" and d.name == "sale.order" for d in decls)

