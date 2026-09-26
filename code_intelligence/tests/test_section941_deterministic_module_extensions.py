"""
code_intelligence/tests/test_section941_deterministic_module_extensions.py

todo/contexte.txt section 941 (Point P): deterministic inspection and extraction
of out-of-perimeter model extensions (Python class names, source files, added
fields, and overridden methods) directly during inheritance dispatch, replacing
ad-hoc regex patching over LLM synthesis.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
import networkx as nx
import pytest

from code_intelligence.rules.structure import (
    ModelExtensionInfo,
    _is_technical_or_transient,
    _extract_ast_class_info,
    inspect_module_cross_domain_extensions,
    format_module_cross_domain_extensions,
    _backfill_missing_module_extension_details,
    _answer_denies_module_extension,
    _correct_module_extension_contradiction,
)
from code_intelligence.agent.context import DispatchContext
from code_intelligence.agent.predispatch_structure import dispatch_inheritance
import code_intelligence.agent.tool_helpers as tool_helpers


def test_is_technical_or_transient():
    assert _is_technical_or_transient("ir.config_parameter") is True
    assert _is_technical_or_transient("res.config.settings") is True
    assert _is_technical_or_transient("onboarding.onboarding.step") is True
    assert _is_technical_or_transient("base.document.layout") is True
    assert _is_technical_or_transient("payment.link.wizard") is True
    assert _is_technical_or_transient("account.invoice.report") is True
    assert _is_technical_or_transient("account.move") is False
    assert _is_technical_or_transient("product.product") is False
    assert _is_technical_or_transient("res.partner") is False


def test_extract_ast_class_info_multi_and_single_inherit(tmp_path: Path):
    src = (
        "from odoo import fields, models\n\n"
        "class AccountMove(models.Model):\n"
        "    _name = 'account.move'\n"
        "    _inherit = ['account.move', 'utm.mixin']\n\n"
        "    team_id = fields.Many2one('crm.team', string='Sales Team')\n"
        "    sale_order_count = fields.Integer(string='Sale Order Count')\n\n"
        "    def unlink(self):\n"
        "        return super().unlink()\n\n"
        "class OtherModel(models.Model):\n"
        "    _inherit = 'product.product'\n"
        "    qty_available = fields.Float('Qty')\n"
    )
    test_file = tmp_path / "models" / "account_move.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text(src, encoding="utf-8")

    info = _extract_ast_class_info(str(test_file), "account.move")
    assert info is not None
    assert info["class_name"] == "AccountMove"
    assert info["inherit"] == ["account.move", "utm.mixin"]
    assert "team_id" in info["fields"]
    assert "sale_order_count" in info["fields"]
    assert "unlink" in info["methods"]

    other_info = _extract_ast_class_info(str(test_file), "product.product")
    assert other_info is not None
    assert other_info["class_name"] == "OtherModel"
    assert other_info["inherit"] == ["product.product"]
    assert "qty_available" in other_info["fields"]


def test_inspect_module_cross_domain_extensions(tmp_path: Path):
    src = (
        "from odoo import fields, models\n\n"
        "class AccountMove(models.Model):\n"
        "    _inherit = 'account.move'\n"
        "    team_id = fields.Many2one('crm.team')\n"
    )
    mod_dir = tmp_path / "sale" / "models"
    mod_dir.mkdir(parents=True, exist_ok=True)
    ext_file = mod_dir / "account_move.py"
    ext_file.write_text(src, encoding="utf-8")

    G = nx.DiGraph()
    G.add_node("module:sale", node_type="Module")
    G.add_node("model:sale.order", node_type="Model", filepaths=[])
    G.add_edge("model:sale.order", "module:sale", edge_type="DEFINED_IN", role="declares")

    G.add_node(
        "model:account.move",
        node_type="Model",
        filepaths=[str(ext_file)],
        filepath_roles={str(ext_file): "extends"},
    )
    G.add_edge("model:account.move", "module:sale", edge_type="DEFINED_IN", role="extends")

    extensions = inspect_module_cross_domain_extensions(G, "sale")
    assert len(extensions) == 1
    assert extensions[0].model_name == "account.move"
    assert extensions[0].class_name == "AccountMove"
    assert extensions[0].is_core is True
    assert "team_id" in extensions[0].fields_added


def test_format_module_cross_domain_extensions():
    ext_info = ModelExtensionInfo(
        model_name="account.move",
        class_name="AccountMove",
        filepath="/srv/odoo/addons/sale/models/account_move.py",
        inherit=["account.move", "utm.mixin"],
        fields_added=["team_id", "sale_order_count"],
        methods_defined=["unlink", "action_post"],
        is_core=True,
    )
    out = format_module_cross_domain_extensions([ext_info], "sale")
    assert "[FAIT DÉTERMINISTIQUE -- EXTENSIONS DU MODULE HORS PÉRIMÈTRE]" in out
    assert "module 'sale'" in out.lower()
    assert "account.move" in out
    assert "AccountMove" in out
    assert "team_id" in out
    assert "unlink" in out

    empty_out = format_module_cross_domain_extensions([], "maintenance")
    assert "n'étend aucun modèle métier natif hors de son propre périmètre" in empty_out


def test_backfill_missing_module_extension_details():
    raw_obs = (
        "[FAIT DÉTERMINISTIQUE -- EXTENSIONS DU MODULE HORS PÉRIMÈTRE]\n"
        "Le module 'sale' étend directement les modèles natifs suivants hors de son propre périmètre :\n"
        "- Modèle 'account.move' (classe Python : `AccountMove` dans models/account_move.py) :\n"
        "  * Héritage : _inherit = ['account.move', 'utm.mixin']\n"
        "  * Champs ajoutés : team_id, sale_order_count\n"
    )
    q_class = "sale.order est-il un nouveau modele ? Quel modele hors vente etend-il, et sous quel nom de classe ?"
    ans_without_class = "sale.order est un nouveau modele. Il etend account.move."
    fixed = _backfill_missing_module_extension_details(ans_without_class, raw_obs, question=q_class)
    assert "AccountMove" in fixed

    ans_with_class = "sale.order est un nouveau modele. Il etend account.move sous la classe AccountMove."
    fixed_noop = _backfill_missing_module_extension_details(ans_with_class, raw_obs, question=q_class)
    assert fixed_noop == ans_with_class

    q_fields = "stock.picking est-il un nouveau modele ? Quels champs cles sont ajoutes au produit ?"
    raw_stock = (
        "[FAIT DÉTERMINISTIQUE -- EXTENSIONS DU MODULE HORS PÉRIMÈTRE]\n"
        "Le module 'stock' étend directement les modèles natifs suivants hors de son propre périmètre :\n"
        "- Modèle 'product.product' (classe Python : `Product` dans models/product.py) :\n"
        "  * Champs ajoutés : qty_available, virtual_available, stock_quant_ids\n"
    )
    ans_fields = "stock.picking est un nouveau modele qui etend product.product."
    fixed_fields = _backfill_missing_module_extension_details(ans_fields, raw_stock, question=q_fields)
    assert "qty_available" in fixed_fields


def test_denial_regex_catches_ne_touche_pas():
    ans = "En conclusion, le module ne touche pas a d'autres modeles natifs en dehors de ce domaine."
    assert _answer_denies_module_extension(ans) is True


def test_dispatch_inheritance_pre_dispatches_inspect_module_extensions(monkeypatch, tmp_path: Path):
    src = (
        "from odoo import fields, models\n\n"
        "class AccountMove(models.Model):\n"
        "    _inherit = 'account.move'\n"
        "    team_id = fields.Many2one('crm.team')\n"
    )
    mod_dir = tmp_path / "sale" / "models"
    mod_dir.mkdir(parents=True, exist_ok=True)
    ext_file = mod_dir / "account_move.py"
    ext_file.write_text(src, encoding="utf-8")

    G = nx.DiGraph()
    G.add_node("module:sale", node_type="Module", filepath=str(mod_dir.parent / "__manifest__.py"))
    G.add_node("model:sale.order", node_type="Model", filepaths=[])
    G.add_edge("model:sale.order", "module:sale", edge_type="DEFINED_IN", role="declares")

    G.add_node(
        "model:account.move",
        node_type="Model",
        filepaths=[str(ext_file)],
        filepath_roles={str(ext_file): "extends"},
    )
    G.add_edge("model:account.move", "module:sale", edge_type="DEFINED_IN", role="extends")

    monkeypatch.setattr(tool_helpers, "_is_custom_module_filepath", lambda fp: False)
    tool_helpers.set_graph_ref(G)

    ctx = DispatchContext(
        G=G,
        concept=SimpleNamespace(
            is_resolved=True, resolved_models=["sale.order"], resolved_modules=["sale"],
        ),
        question="sale.order est-il un nouveau modele ou une extension ? Quel modele natif hors vente etend-il ?",
        tool_map={},
        resolved_user_group_xmlids=[],
        trace_logger=MagicMock(),
        trace_id="test",
        hop_cap=20,
    )
    dispatch_inheritance(ctx)

    assert any(k and k[0] == "inspect_module_extensions" for k in ctx.seen_calls)
    assert any("[FAIT DÉTERMINISTIQUE -- EXTENSIONS DU MODULE HORS PÉRIMÈTRE]" in obs for obs in ctx.tool_observations)
    assert "DETERMINISTIC PRE-DISPATCH -- INHERITANCE & MODULE EXTENSIONS" in ctx.system_prompt_suffix
