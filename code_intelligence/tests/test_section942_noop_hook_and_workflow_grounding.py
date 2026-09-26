"""
code_intelligence/tests/test_section942_noop_hook_and_workflow_grounding.py

todo/contexte.txt section 939 / section 942 (Point R): deterministic AST-based
detection of no-op hooks (empty body, pass, return True/False/None/{}/[],
NotImplementedError), annotation of read_source_code observations, prompt
grounding, and stripping of hallucinated business effects (such as tax
recalculation during action_confirm).
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
import networkx as nx
import pytest

from code_intelligence.rules.source_callees import (
    inspect_noop_hook_method,
    format_noop_hook_note,
)
from code_intelligence.agent.tools.introspection import read_precise_source_code
from code_intelligence.rules.workflow import (
    _correct_noop_hook_hallucinations,
    _backfill_action_confirm_workflow_details,
)
from code_intelligence.agent.prompts import (
    EFFECT_GROUNDING_RULE,
    CI_SYSTEM_PROMPT,
    build_synthesis_prompt,
)


def test_inspect_noop_hook_method_variations():
    c_tax = (
        "    def validate_taxes_on_sales_order(self):\n"
        "        # Override for correct taxcloud computation\n"
        "        # when using coupon and delivery\n"
        "        return True\n"
    )
    res = inspect_noop_hook_method(c_tax)
    assert res is not None
    assert res[0] == "validate_taxes_on_sales_order"
    assert "retourne True" in res[1]

    c_pass = "def hook_pass(self):\n    '''Docstring'''\n    pass\n"
    res_pass = inspect_noop_hook_method(c_pass)
    assert res_pass == ("hook_pass", "pass")

    c_empty = "def hook_empty(self):\n    '''Docstring only'''\n"
    res_empty = inspect_noop_hook_method(c_empty)
    assert res_empty is not None
    assert res_empty[0] == "hook_empty"
    assert "vide" in res_empty[1]

    c_none = "def hook_none(self):\n    return None\n"
    assert inspect_noop_hook_method(c_none) == ("hook_none", "retourne None")

    c_bare = "def hook_bare(self):\n    return\n"
    assert inspect_noop_hook_method(c_bare) == ("hook_bare", "retourne None")

    c_dict = "def hook_dict(self):\n    return {}\n"
    assert inspect_noop_hook_method(c_dict) == ("hook_dict", "retourne un conteneur vide")

    c_ellipsis = "def hook_ellipsis(self):\n    ...\n"
    assert inspect_noop_hook_method(c_ellipsis) == ("hook_ellipsis", "...")

    c_not_impl = "def hook_not_impl(self):\n    raise NotImplementedError()\n"
    assert inspect_noop_hook_method(c_not_impl) == ("hook_not_impl", "lève NotImplementedError")


def test_inspect_noop_hook_method_real_methods_return_none():
    real1 = (
        "def _can_be_confirmed(self):\n"
        "    self.ensure_one()\n"
        "    return self.state in {'draft', 'sent'}\n"
    )
    assert inspect_noop_hook_method(real1) is None

    real2 = (
        "def action_confirm(self):\n"
        "    self.write({'state': 'sale'})\n"
        "    return True\n"
    )
    assert inspect_noop_hook_method(real2) is None

    real3 = (
        "def compute_total(self):\n"
        "    return 10 + 20\n"
    )
    assert inspect_noop_hook_method(real3) is None


def test_format_noop_hook_note():
    note = format_noop_hook_note("validate_taxes_on_sales_order", "retourne True")
    assert "[NOTE DÉTERMINISTIQUE -- HOOK SANS EFFET / NO-OP]" in note
    assert "validate_taxes_on_sales_order" in note
    assert "retourne True" in note
    assert "Ne PAS lui attribuer d'effet métier" in note


def test_read_precise_source_code_annotates_noop_hook(tmp_path: Path):
    src = (
        "class SaleOrder:\n"
        "    def validate_taxes_on_sales_order(self):\n"
        "        # tax hook\n"
        "        return True\n"
    )
    test_file = tmp_path / "sale_order.py"
    test_file.write_text(src, encoding="utf-8")

    out = read_precise_source_code(str(test_file), line_start=2, line_end=4, include_citation=False)
    assert "validate_taxes_on_sales_order" in out
    assert "return True" in out
    assert "[NOTE DÉTERMINISTIQUE -- HOOK SANS EFFET / NO-OP]" in out
    assert "retourne True" in out


def test_correct_noop_hook_hallucinations_strips_tax_claims():
    raw_obs = (
        "[NOTE DÉTERMINISTIQUE -- HOOK SANS EFFET / NO-OP]\n"
        "La méthode 'validate_taxes_on_sales_order' est un hook sans effet / no-op (retourne True)."
    )
    answer = (
        "### Ce qui se passe lors de la confirmation\n\n"
        "- **Changement d’état** : passe à En cours.\n"
        "- **Validation des taxes** : les taxes sont recalculées et validées pour chaque ligne.\n"
        "- **Abonnement du client** : le client est abonné.\n\n"
        "En résumé, la confirmation transforme la commande, applique les taxes, et notifie le client."
    )
    cleaned = _correct_noop_hook_hallucinations(answer, raw_obs)
    assert "Validation des taxes" not in cleaned
    assert "les taxes sont recalculées" not in cleaned
    assert "applique les taxes" not in cleaned
    assert "- **Changement d’état** : passe à En cours." in cleaned
    assert "- **Abonnement du client** : le client est abonné." in cleaned

    # When no no-op hook in observations, leaves answer intact
    unchanged = _correct_noop_hook_hallucinations(answer, "No hooks here")
    assert unchanged == answer


def test_backfill_action_confirm_workflow_details():
    raw_obs = (
        "def _can_be_confirmed(self):\n"
        "    return self.state in {'draft', 'sent'}\n"
    )
    q = "Que se passe-t-il exactement quand on confirme une commande de vente (action_confirm) ?"
    answer = (
        "### Ce qui se passe lors de la confirmation\n\n"
        "- **Changement d’état** : la commande passe de *Brouillon* ou *Envoyée* à *En cours* (état « sale »).\n"
        "- **Abonnement du client** : le client est abonné."
    )
    fixed = _backfill_action_confirm_workflow_details(answer, raw_obs, question=q)
    assert "Vérification préalable" in fixed
    assert "Validation analytique" in fixed
    assert "Changement d’état et date" in fixed
    assert "Brouillon" in fixed
    assert "Envoyée" in fixed

    # When answer already explains precondition check, no duplicate replacement
    already_good = (
        "### Confirmation\n\n"
        "- **Vérification préalable** : le système vérifie que les commandes sont à l'état brouillon ou envoyée.\n"
        "- **Changement d'état** : passe à l'état sale."
    )
    res_good = _backfill_action_confirm_workflow_details(already_good, raw_obs, question=q)
    assert res_good == already_good


def test_effect_grounding_rule_in_prompts():
    assert "hook" in EFFECT_GROUNDING_RULE.lower()
    assert "no-op" in EFFECT_GROUNDING_RULE.lower()
    assert EFFECT_GROUNDING_RULE in CI_SYSTEM_PROMPT
    assert EFFECT_GROUNDING_RULE in build_synthesis_prompt("Test question", ["Obs 1"], ["describe_workflow"])
