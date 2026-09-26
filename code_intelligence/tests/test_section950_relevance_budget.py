"""
code_intelligence/tests/test_section950_relevance_budget.py

Unit and integration tests for Section 950:
- Generic relevance budget allocation and water-filling (relevance_budget.py).
- Generalization of question-aware relevance ranking to who_has_access_to,
  evaluate_record_rules, and analyze_method_override_chain (resolving Section 948 point 1).
"""

from unittest.mock import MagicMock
import networkx as nx
import pytest

from code_intelligence.rules.relevance_budget import (
    _significant_tokens,
    _relevance_score,
    _rerank_by_relevance,
    _protected_prefix_end,
    _waterfill_with_protected_minimum,
    assemble_relevance_ranked_blocks,
)
from code_intelligence.rules.access_evaluator import who_has_access_to
from code_intelligence.rules.record_rules import evaluate_record_rules
from code_intelligence.rules.override_composer import analyze_method_override_chain_with_evidence
import code_intelligence.agent.tool_helpers as tool_helpers


def test_significant_tokens_excludes_stopwords():
    tokens = _significant_tokens("Le vendeur peut-il voir les commandes de vente avec son groupe ?")
    assert "vendeur" in tokens
    assert "commandes" in tokens
    assert "vente" in tokens
    assert "groupe" in tokens
    assert "avec" not in tokens
    assert "peut" not in tokens
    assert "les" not in tokens


def test_relevance_score_overlap_bonus():
    q = "Quelle règle s'applique sur le fiscalyear lock date de la société ?"
    t_relevant = "Vérification de la date de clôture : _check_fiscalyear_lock_date sur res.company."
    t_irrelevant = "Contrôle des taxes étrangères incompatibles avec le pays."
    assert _relevance_score(t_relevant, q) > _relevance_score(t_irrelevant, q)


def test_rerank_by_relevance_preserves_order_without_question():
    items = ["item_a", "item_b", "item_c"]
    assert _rerank_by_relevance(items, lambda x: x, None) == items
    assert _rerank_by_relevance(items, lambda x: x, "") == items


def test_protected_prefix_end():
    # Single line -> 0
    assert _protected_prefix_end("Header without newline") == 0

    # Two lines -> length of first 2 lines
    two_lines = "Header line\nFirst finding line\nSecond finding line"
    assert _protected_prefix_end(two_lines) == len("Header line\nFirst finding line")

    # Three lines with bullet continuation
    bullet = "Header line\n* Required Groups: group_user\n  * detail bullet"
    assert _protected_prefix_end(bullet) == len(bullet)


def test_assemble_relevance_ranked_blocks_fits_all():
    blocks = ["Block 1: hello", "Block 2: world"]
    res = assemble_relevance_ranked_blocks(blocks, 100, question="anything")
    assert res == "Block 1: hello\nBlock 2: world"


def test_assemble_relevance_ranked_blocks_prioritizes_relevant_block():
    b_first = "Block 1: General sales information\nDetails about lines"
    b_second = "Block 2: Fiscalyear lock date validation\nDetails about lock date exception"
    blocks = [b_first, b_second]

    # With a small budget that cannot fit both blocks
    budget = len(b_second) + 20
    q = "fiscalyear lock date"
    res = assemble_relevance_ranked_blocks(blocks, budget, question=q)
    assert "Fiscalyear lock date" in res


def test_who_has_access_to_relevance_ranked_under_tight_budget(monkeypatch):
    G = nx.DiGraph()
    G.add_node("model:test.model", node_type="Model", name="Test Model")
    G.add_node("group:base.group_user", node_type="Group", name="User")

    # Add access rights
    G.add_edge("group:base.group_user", "model:test.model", perm_read=True, perm_write=True, perm_create=False, perm_unlink=False)

    monkeypatch.setattr(tool_helpers, "get_current_question", lambda: "Un utilisateur a-t-il le droit d'écriture (write) sur ce modèle ?")

    # Patch budget to be very small, forcing a cut
    from code_intelligence.agent import context
    orig_caps = dict(context.PER_TOOL_OBSERVATION_CAPS)
    monkeypatch.setattr(context, "PER_TOOL_OBSERVATION_CAPS", {**orig_caps, "who_has_access_to": 150})

    res = who_has_access_to(G, "test.model", permission="all")
    # [WRITE] must survive because the question is about write access
    assert "[WRITE]" in res.summary_text


def test_evaluate_record_rules_relevance_ranked_under_tight_budget(monkeypatch):
    G = nx.DiGraph()
    G.add_node("model:test.model", node_type="Model", name="Test Model")

    # Global rule
    r_node = "rule:test_global_rule"
    G.add_node(r_node, node_type="Rule", rule_name="Multi-company test", domain_force="[('company_id', '=', 1)]", global_rule=True)
    G.add_edge(r_node, "model:test.model", edge_type="APPLIES_TO")

    monkeypatch.setattr(tool_helpers, "get_current_question", lambda: "Quelles sont les règles globales multi-company ?")

    from code_intelligence.agent import context
    orig_caps = dict(context.PER_TOOL_OBSERVATION_CAPS)
    monkeypatch.setattr(context, "PER_TOOL_OBSERVATION_CAPS", {**orig_caps, "evaluate_record_rules": 200})

    res = evaluate_record_rules(G, "test.model")
    assert "Règles Globales" in res.summary_text


def test_analyze_method_override_chain_relevance_ranked_under_tight_budget(monkeypatch, tmp_path):
    src1 = (
        "class SaleOrder(models.Model):\n"
        "    def action_confirm(self):\n"
        "        pass\n"
    )
    src2 = (
        "class SaleOrder(models.Model):\n"
        "    def action_confirm(self):\n"
        "        # special lock date check\n"
        "        raise UserError('Fiscalyear lock date reached')\n"
    )
    f1 = tmp_path / "sale" / "sale_order.py"
    f1.parent.mkdir(parents=True, exist_ok=True)
    f1.write_text(src1, encoding="utf-8")

    f2 = tmp_path / "account" / "sale_order.py"
    f2.parent.mkdir(parents=True, exist_ok=True)
    f2.write_text(src2, encoding="utf-8")

    from code_intelligence.rules.override_unguarded import MethodOverrideSite
    sites = [
        MethodOverrideSite(module="sale", filepath=str(f1), lineno=2, end_lineno=3),
        MethodOverrideSite(module="account", filepath=str(f2), lineno=2, end_lineno=4),
    ]

    monkeypatch.setattr(
        "code_intelligence.rules.override_composer.resolve_method_override_chain",
        lambda G, m, meth: sites,
    )
    monkeypatch.setattr(
        tool_helpers, "get_current_question",
        lambda: "Comment l'extension account vérifie-t-elle le fiscalyear lock date ?",
    )

    from code_intelligence.agent import context
    orig_caps = dict(context.PER_TOOL_OBSERVATION_CAPS)
    # Give budget sufficient only for one site block (~220 chars) plus header (~120 chars)
    monkeypatch.setattr(context, "PER_TOOL_OBSERVATION_CAPS", {**orig_caps, "analyze_method_override_chain": 350})

    G = nx.DiGraph()
    res = analyze_method_override_chain_with_evidence(G, "sale.order", "action_confirm")
    # Site 2 (module 'account' with fiscalyear lock date) must be prioritized over site 1
    assert "module 'account'" in res.summary_text

