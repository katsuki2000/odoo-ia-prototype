"""
code_intelligence/tests/test_section945_point_q_alignment.py

todo/contexte.txt Section 945 (Point Q resolution):
- Non-res functional business models are prioritized over base registry models (res.*)
  in inspect_module_cross_domain_extensions so account.move/AccountMove is presented first for sale/purchase.
- _backfill_missing_module_extension_details respects existing class names and targets
  the cited model without appending extraneous entries.
- _correct_module_extension_contradiction does not append noisy 25-model lists on singular
  model inquiries when an extended model is already cited.
- native_n1_question_bank.json SAL-Q3 expected_tools removes analyze_method_override_chain.
"""

import json
from pathlib import Path
import networkx as nx
import pytest

from code_intelligence.rules.structure import (
    ModelExtensionInfo,
    inspect_module_cross_domain_extensions,
    _backfill_missing_module_extension_details,
    _correct_module_extension_contradiction,
)


def test_inspect_module_cross_domain_extensions_prioritizes_business_models():
    G = nx.DiGraph()
    G.add_node("module:sale", node_type="Module")
    G.add_node("model:sale.order", node_type="Model", filepaths=[])
    G.add_edge("model:sale.order", "module:sale", edge_type="DEFINED_IN", role="declares")

    # res.company has high degree (e.g. 200)
    G.add_node("model:res.company", node_type="Model", filepaths=[])
    G.add_edge("model:res.company", "module:sale", edge_type="DEFINED_IN", role="extends")
    for i in range(200):
        dummy = f"model:dummy_{i}"
        G.add_node(dummy, node_type="Model")
        G.add_edge(dummy, "model:res.company", edge_type="RELATION")

    # account.move has lower degree (e.g. 50)
    G.add_node("model:account.move", node_type="Model", filepaths=[])
    G.add_edge("model:account.move", "module:sale", edge_type="DEFINED_IN", role="extends")
    for i in range(50):
        dummy = f"model:dummy_acc_{i}"
        G.add_node(dummy, node_type="Model")
        G.add_edge(dummy, "model:account.move", edge_type="RELATION")

    exts = inspect_module_cross_domain_extensions(G, "sale")
    assert len(exts) == 2
    # account.move (business model) must come before res.company (base registry)
    assert exts[0].model_name == "account.move"
    assert exts[1].model_name == "res.company"


def test_backfill_does_not_add_redundant_class_name():
    raw_obs = (
        "[FAIT DÉTERMINISTIQUE -- EXTENSIONS DU MODULE HORS PÉRIMÈTRE]\n"
        "Le module 'sale' étend directement les modèles natifs suivants hors de son propre périmètre :\n"
        "- Modèle 'account.move' (classe Python : `AccountMove` dans models/account_move.py) :\n"
        "  * Héritage : _inherit = ['account.move', 'utm.mixin']\n"
        "- Modèle 'res.partner' (classe Python : `ResPartner` dans models/res_partner.py) :\n"
        "  * Héritage : _inherit = ['res.partner']\n"
    )
    q = "sale.order est-il un nouveau modele ? Quel modele natif hors vente etend-il, et sous quel nom de classe ?"
    ans = "sale.order est un nouveau modele. Il etend account.move via la classe AccountMove."
    fixed = _backfill_missing_module_extension_details(ans, raw_obs, question=q)
    assert fixed == ans
    assert "ResPartner" not in fixed


def test_backfill_targets_cited_model_when_class_missing():
    raw_obs = (
        "[FAIT DÉTERMINISTIQUE -- EXTENSIONS DU MODULE HORS PÉRIMÈTRE]\n"
        "Le module 'sale' étend directement les modèles natifs suivants hors de son propre périmètre :\n"
        "- Modèle 'res.company' (classe Python : `ResCompany` dans models/res_company.py) :\n"
        "  * Héritage : _inherit = ['res.company']\n"
        "- Modèle 'account.move' (classe Python : `AccountMove` dans models/account_move.py) :\n"
        "  * Héritage : _inherit = ['account.move', 'utm.mixin']\n"
    )
    q = "sale.order est-il un nouveau modele ? Quel modele natif hors vente etend-il, et sous quel nom de classe ?"
    ans = "sale.order est un nouveau modele. Le module sale etend le modele account.move."
    fixed = _backfill_missing_module_extension_details(ans, raw_obs, question=q)
    assert "AccountMove" in fixed
    assert "Nom de classe Python étendant 'account.move' : `AccountMove`" in fixed
    assert "ResCompany" not in fixed


def test_singular_inquiry_does_not_append_25_models_list():
    raw = (
        "Modules implicated for model 'sale.order': sale (declares).\n"
        "Module 'sale' defines or extends the following models: "
        + ", ".join(f"model_{i} (extends)" for i in range(25))
        + ", account.move (extends)."
    )
    q = "sale.order est-il un nouveau modele ou une extension ? Quel modele natif hors du perimetre 'vente' ce module etend-il directement, et sous quel nom de classe ?"
    ans = (
        "### Nature du modèle sale.order\n\n"
        "- sale.order est un nouveau modèle.\n\n"
        "### Extension directe\n\n"
        "- Le module sale étend directement le modèle natif account.move sous la classe AccountMove."
    )
    fixed = _correct_module_extension_contradiction(ans, raw, question=q)
    # Must not append "À noter : ce module étend bien 26 modèle(s)"
    assert "À noter : ce module étend bien" not in fixed
    assert fixed == ans


def test_singular_inquiry_still_neutralizes_explicit_denial():
    raw = (
        "Modules implicated for model 'sale.order': sale (declares).\n"
        "Module 'sale' defines or extends the following models: account.move (extends)."
    )
    q = "sale.order est-il un nouveau modele ou une extension ? Quel modele natif hors du perimetre 'vente' ce module etend-il directement ?"
    ans = "sale.order est un nouveau modèle. Le module n'étend aucun modèle natif hors de son propre périmètre."
    fixed = _correct_module_extension_contradiction(ans, raw, question=q)
    assert "n'étend aucun modèle" not in fixed
    assert "account.move" in fixed


def test_native_n1_question_bank_sal_q3_expected_tools():
    qbank_path = Path(__file__).resolve().parents[2] / "tests" / "native_n1_question_bank.json"
    with open(qbank_path, encoding="utf-8") as f:
        data = json.load(f)
    questions = data.get("questions", data)
    sal_q3 = next((q for q in questions if q.get("id") == "SAL-Q3"), None)
    assert sal_q3 is not None
    assert "analyze_method_override_chain" not in sal_q3.get("expected_tools", [])
    assert "trace_full_inheritance" in sal_q3.get("expected_tools", [])
    assert "list_involved_modules" in sal_q3.get("expected_tools", [])
