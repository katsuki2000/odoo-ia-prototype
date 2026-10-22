"""AST-based no-op hook notes in source reads and synthesis prompt grounding."""

from pathlib import Path
import networkx as nx

from code_intelligence.rules.source_callees import (
    inspect_noop_hook_method,
    format_noop_hook_note,
)
from code_intelligence.agent.tools.introspection import read_precise_source_code
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


def test_read_precise_source_code_annotates_noop_hook(tmp_path: Path, monkeypatch):
    src = (
        "class SaleOrder:\n"
        "    def validate_taxes_on_sales_order(self):\n"
        "        # tax hook\n"
        "        return True\n"
    )
    from config import settings
    monkeypatch.setattr(settings, "CUSTOM_ADDONS_PATH", str(tmp_path))
    test_file = tmp_path / "sale_order.py"
    test_file.write_text(src, encoding="utf-8")

    out = read_precise_source_code(str(test_file), line_start=2, line_end=4, include_citation=False)
    assert "validate_taxes_on_sales_order" in out
    assert "return True" in out
    assert "[NOTE DÉTERMINISTIQUE -- HOOK SANS EFFET / NO-OP]" in out
    assert "retourne True" in out


def test_effect_grounding_rule_in_prompts():
    assert "hook" in EFFECT_GROUNDING_RULE.lower()
    assert "no-op" in EFFECT_GROUNDING_RULE.lower()
    assert EFFECT_GROUNDING_RULE in CI_SYSTEM_PROMPT
    assert EFFECT_GROUNDING_RULE in build_synthesis_prompt("Test question", ["Obs 1"], ["describe_workflow"])
