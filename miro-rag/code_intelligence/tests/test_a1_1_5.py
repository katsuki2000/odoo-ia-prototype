"""
code_intelligence/tests/test_a1_1_5.py

Unit tests for Task A1.1.5: Method context extraction (@api.model, @api.model_create_multi vs instance method).
Tests 3 cases + real corpus file:
  1. Instance method -> api_model=False, is_instance_method=True
  2. @api.model method -> api_model=True, is_instance_method=False
  3. @api.model_create_multi method -> api_model=True, is_instance_method=False
  4. Real corpus test on sale/res_partner.py
"""

import tempfile
from pathlib import Path

from code_intelligence.python_extractor import extract_odoo_models_from_file


def test_method_context_extraction():
    """Test method context distinction: @api.model vs @api.model_create_multi vs instance method."""
    code = """
from odoo import models, api

class SaleOrder(models.Model):
    _name = 'sale.order'

    def action_confirm(self):
        pass

    @api.model
    def default_get(self, fields_list):
        pass

    @api.model_create_multi
    def create(self, vals_list):
        pass
"""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(code)
        f_path = Path(f.name)

    try:
        models_found = extract_odoo_models_from_file(f_path)
        assert len(models_found) == 1
        model = models_found[0]
        methods_map = {m.name: m for m in model.methods}

        # 1. Instance method: action_confirm
        assert "action_confirm" in methods_map
        m_instance = methods_map["action_confirm"]
        assert m_instance.api_model is False
        assert m_instance.is_instance_method is True

        # 2. @api.model method: default_get
        assert "default_get" in methods_map
        m_model = methods_map["default_get"]
        assert m_model.api_model is True
        assert m_model.is_instance_method is False

        # 3. @api.model_create_multi method: create
        assert "create" in methods_map
        m_create = methods_map["create"]
        assert m_create.api_model is True
        assert m_create.is_instance_method is False

    finally:
        f_path.unlink()


def test_real_corpus_res_partner_model_method():
    """Test @api.model method extraction on real sale/res_partner.py file."""
    corpus_root = Path(__file__).resolve().parent.parent.parent / "fake_data" / "code"
    res_partner_file = corpus_root / "sale" / "res_partner.py"

    if res_partner_file.exists():
        models_found = extract_odoo_models_from_file(res_partner_file)
        res_partner = next((m for m in models_found if m.class_name == "ResPartner"), None)
        assert res_partner is not None

        methods_map = {m.name: m for m in res_partner.methods}
        assert "_get_sale_order_domain_count" in methods_map
        m_domain = methods_map["_get_sale_order_domain_count"]
        assert m_domain.api_model is True
        assert m_domain.is_instance_method is False
