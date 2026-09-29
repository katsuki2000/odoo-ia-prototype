"""
Tests for Section 951:
1. SAL-Q2: Technical groups (format_technical_group_note / NOTE DE CONFIGURATION)
   recognized as grounded in _flag_ungrounded_group_xmlids.
2. SAL-Q3: Declaring module prioritized in target_mods_to_inspect for dispatch_inheritance.
3. PUR-Q3 & ACC-Q2: question bank expected_tools and reference_answer alignment.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import networkx as nx
import pytest

from code_intelligence.agent import tool_helpers
from code_intelligence.agent.access_guards import _flag_ungrounded_group_xmlids
from code_intelligence.agent.context import DispatchContext
from code_intelligence.agent.predispatch_structure import dispatch_inheritance
from code_intelligence.agent.predispatch_access import dispatch_who_has_access_to
from code_intelligence.rules.technical_groups import TechnicalGroup, format_technical_group_note
from code_intelligence.agent.resolver import resolve_business_term
from code_intelligence.rules.workflow import (
    _backfill_backorder_policy_facts,
    _backfill_confirmation_lock_fact,
)
from code_intelligence.rules.security_locks import _backfill_fiscal_lock_scope_fact


def test_sal_q2_technical_group_not_flagged_as_ungrounded():
    tech_note = format_technical_group_note([
        TechnicalGroup("sale.group_auto_done_setting", "group_auto_done_setting", "Lock Confirmed Sales")
    ])
    raw_output = f"""
Analyse des verrous Python ([sale_order.py:L940-L980](file:///path/sale_order.py#L940-L980)):
  - Groupe(s) technique(s) requis detecte(s) (has_group): base.group_user

{tech_note}
"""
    answer = (
        "La commande est verrouillée si l'utilisateur appartient au groupe "
        "`sale.group_auto_done_setting` ('Lock Confirmed Sales')."
    )
    result = _flag_ungrounded_group_xmlids(answer, raw_output)
    assert "GROUPE(S) NON VÉRIFIÉ(S)" not in result
    assert result == answer


def test_sal_q2_unknown_group_still_flagged():
    tech_note = format_technical_group_note([
        TechnicalGroup("sale.group_auto_done_setting", "group_auto_done_setting", "Lock Confirmed Sales")
    ])
    raw_output = f"""
Analyse des verrous Python ([sale_order.py:L940-L980](file:///path/sale_order.py#L940-L980)):
  - Groupe(s) technique(s) requis detecte(s) (has_group): base.group_user

{tech_note}
"""
    answer = (
        "La commande est verrouillée si l'utilisateur appartient au groupe "
        "`sale.group_auto_done_setting` et au groupe `sale.group_invented_admin`."
    )
    result = _flag_ungrounded_group_xmlids(answer, raw_output)
    assert "GROUPE(S) NON VÉRIFIÉ(S)" in result
    assert "sale.group_invented_admin" in result
    assert "sale.group_auto_done_setting" not in result.split("GROUPE(S) NON VÉRIFIÉ(S) :")[1].split(" mentionné")[0]


class RecordingTool:
    def __init__(self):
        self.calls = []

    def invoke(self, args):
        self.calls.append(args["model_name"])
        return f"observation for {args['model_name']}"


class FakeTraceLogger:
    def log_hop(self, *args, **kwargs):
        pass


def test_dispatch_inheritance_prioritizes_declaring_module(monkeypatch):
    G = nx.DiGraph()
    G.add_node("model:sale.order", node_type="Model", name="sale.order", filepaths=[])
    G.add_node("module:sale", node_type="Module", filepath="/srv/core/sale/__manifest__.py")
    G.add_edge("model:sale.order", "module:sale", edge_type="DEFINED_IN", role="declares")
    G.add_node(
        "module:account_invoice_section_sale_order",
        node_type="Module",
        filepath="/srv/third_party/account_invoice_section_sale_order/__manifest__.py",
    )
    G.add_edge(
        "model:sale.order",
        "module:account_invoice_section_sale_order",
        edge_type="DEFINED_IN",
        role="extends",
    )

    monkeypatch.setattr(
        tool_helpers, "_is_custom_module_filepath", lambda fp: "third_party" in fp,
    )
    tool_helpers.set_graph_ref(G)
    mod_tool = RecordingTool()
    question = (
        "sale.order est-il un nouveau modele ou une extension ? Quel modele natif "
        "hors du perimetre 'vente' ce module etend-il directement, et sous quel nom de classe ?"
    )
    ctx = DispatchContext(
        G=G,
        concept=SimpleNamespace(
            is_resolved=True, resolved_models=["sale.order"], resolved_modules=[],
        ),
        question=question,
        tool_map={"list_involved_modules": mod_tool},
        resolved_user_group_xmlids=[],
        trace_logger=FakeTraceLogger(),
        trace_id="test_sal_q3",
        hop_cap=20,
    )
    dispatch_inheritance(ctx)
    assert mod_tool.calls
    assert mod_tool.calls[0] == "sale"


def test_workflow_alias_wins_over_shared_method_symbol():
    """A shared method name must not make unrelated models consume dispatch slots."""
    graph = nx.DiGraph()
    for model in ("sale.order", "stock.track.confirmation", "stock.picking", "hr.leave"):
        graph.add_node(f"model:{model}", node_type="Model", name=model)

    question = (
        "Que se passe-t-il exactement quand on confirme une commande de vente "
        "(action_confirm), et dans quel cas est-elle automatiquement verrouillee (locked) juste apres ?"
    )
    concept = resolve_business_term(question, graph, llm=None)

    assert concept.resolved_models == ["sale.order"]


def test_unique_button_model_wins_over_generic_commande_alias():
    graph = nx.DiGraph()
    graph.add_node("model:purchase.order", node_type="Model", name="purchase.order")
    graph.add_node("model:sale.order", node_type="Model", name="sale.order")
    graph.add_node(
        "button:purchase.order.button_confirm",
        node_type="Button", name="button_confirm", model="purchase.order",
    )
    question = (
        "Que se passe-t-il quand on clique sur 'Confirm Order' "
        "(button_confirm) pour une commande eligible à l'approbation directe ?"
    )
    concept = resolve_business_term(question, graph, llm=None)
    assert concept.resolved_models == ["purchase.order"]


def test_confirmation_lock_fact_removes_false_no_lock_claim():
    raw = "_should_be_locked()\ncreate_uid.has_group('sale.group_auto_done_setting')\naction_lock()\nlocked=True"
    answer = "La confirmation passe la commande à l'état sale. Aucun verrouillage automatique n'est mentionné."
    result = _backfill_confirmation_lock_fact(answer, raw, "confirmer une commande de vente (action_confirm)")
    assert "Aucun verrouillage" not in result
    assert "create_uid" in result
    assert "pas de l'utilisateur qui confirme" in result
    assert "option de configuration globale" not in result
    assert "ne dépend pas d'un groupe spécifique" not in result


def test_confirmation_lock_fact_replaces_configuration_paraphrase_with_creator_guard():
    raw = "_should_be_locked()\ncreate_uid.has_group('sale.group_auto_done_setting')\naction_lock()\nlocked=True"
    answer = (
        "### Cas de verrouillage automatique\n\n"
        "Le verrouillage dépend d'une configuration globale et de l'utilisateur qui confirme."
    )
    result = _backfill_confirmation_lock_fact(answer, raw, "confirmer une commande de vente (action_confirm)")
    assert "configuration globale" not in result
    assert "groupe du créateur" in result


def test_backorder_fact_preserves_all_picking_type_branches():
    raw = "button_validate() picking_type_id.create_backorder == 'never' create_backorder == 'always' create_backorder == 'ask'"
    result = _backfill_backorder_policy_facts(
        "La validation partielle génère automatiquement un backorder.", raw,
        "valider un transfert avec des quantités traitées inférieures",
    )
    assert "ne crée pas toujours automatiquement" in result
    assert "never" in result and "always" in result and "ask" in result
    assert "génère automatiquement un backorder" not in result
    assert "Création du backorder" not in result


def test_backorder_fact_removes_creation_automatic_and_example_heading():
    raw = "create_backorder == 'never' create_backorder == 'always' create_backorder == 'ask'"
    answer = (
        "Le système déclenche une création automatique d'un bon de sortie partiel (backorder).\n\n"
        "### Exemple concret\nSi 60 unités sont traitées, un reliquat est créé."
    )
    result = _backfill_backorder_policy_facts(
        answer, raw, "valider un transfert avec des quantités traitées inférieures"
    )
    assert "Le système déclenche une création automatique" not in result
    assert "Exemple concret" not in result
    assert "ne crée pas toujours automatiquement" in result


def test_fiscal_lock_fact_does_not_exempt_manager_from_fiscalyear_lock():
    raw = (
        "_get_user_fiscal_lock_date period_lock_date fiscalyear_lock_date "
        "account.group_account_manager _check_fiscalyear_lock_date"
    )
    result = _backfill_fiscal_lock_scope_fact(
        "Le Billing Administrator peut poster jusqu'à la date de clôture.", raw,
        "un Billing Administrator peut-il poster avant la lock date ?",
    )
    assert "ne concerne que `period_lock_date`" in result
    assert "bloque donc aussi" in result
    assert "peut poster jusqu'à" not in result
    assert "société mère" not in result


def test_fiscal_lock_fact_keeps_a_plain_language_verdict_and_removes_acl_noise():
    raw = "_get_user_fiscal_lock_date period_lock_date fiscalyear_lock_date account.group_account_manager _check_fiscalyear_lock_date"
    answer = (
        "### Règles de blocage comptable\n\n"
        "[FAIT DÉTERMINISTIQUE] Précision d'héritage de droits: account.group_account_manager "
        "hérite d'une ACL via implied_ids."
    )
    result = _backfill_fiscal_lock_scope_fact(
        answer, raw, "un Billing Administrator peut-il poster avant la lock date ?"
    )
    assert "Précision d'héritage" not in result
    assert "**Réponse : non.**" in result


def test_question_bank_pur_q3_and_acc_q2_aligned():
    qbank_path = Path(__file__).resolve().parents[2] / "tests" / "native_n1_question_bank.json"
    with open(qbank_path, encoding="utf-8") as f:
        data = json.load(f)
    questions = data.get("questions", data)

    pur_q3 = next((q for q in questions if q.get("id") == "PUR-Q3"), None)
    assert pur_q3 is not None
    assert "analyze_method_override_chain" not in pur_q3.get("expected_tools", [])
    assert "trace_full_inheritance" in pur_q3.get("expected_tools", [])
    assert "list_involved_modules" in pur_q3.get("expected_tools", [])
    acc_q2 = next((q for q in questions if q.get("id") == "ACC-Q2"), None)
    assert acc_q2 is not None
    assert "describe_workflow" not in acc_q2.get("expected_tools", [])
    assert "analyze_security_locks" in acc_q2.get("expected_tools", [])
    assert "read_source_code" in acc_q2.get("expected_tools", [])
    assert "fiscalyear_lock_date" in acc_q2.get("reference_answer", "")
    assert "period_lock_date" in acc_q2.get("reference_answer", "")


def test_access_dispatch_covers_all_resolved_models():
    G = nx.DiGraph()
    for model in ("stock.quant", "stock.move.line"):
        G.add_node(f"model:{model}", node_type="Model", name=model)

    tool = RecordingTool()
    ctx = DispatchContext(
        G=G,
        concept=SimpleNamespace(
            is_resolved=True,
            resolved_models=["stock.quant", "stock.move.line"],
            resolved_modules=[],
        ),
        question=(
            "Un simple employe peut-il consulter stock.quant et modifier "
            "stock.move.line ?"
        ),
        tool_map={"who_has_access_to": tool},
        resolved_user_group_xmlids=[],
        trace_logger=FakeTraceLogger(),
        trace_id="test_access_all_models",
        hop_cap=20,
    )

    dispatch_who_has_access_to(ctx)

    assert tool.calls == ["stock.quant", "stock.move.line"]

def test_button_path_detects_stock_multi_locations_technical_group():
    G = nx.DiGraph()
    G.add_node("model:stock.picking", node_type="Model", name="stock.picking")
    G.add_node("group:stock.group_stock_multi_locations", node_type="Group", name="Manage Multiple Stock Locations")
    G.add_node("field:res.config.settings.group_stock_multi_locations", node_type="Field", category_id="base.module_category_hidden")
    from code_intelligence.rules.button_path import button_execution_path
    G.add_node("method:stock.picking.button_scrap", node_type="Method", name="button_scrap", filepath="addons/stock/models/stock_picking.py", lineno=1, end_lineno=10)
    G.add_node("state:stock.picking.draft", node_type="State")
    G.add_node("state:stock.picking.done", node_type="State")
    G.add_edge(
        "state:stock.picking.draft",
        "state:stock.picking.done",
        edge_type="TRANSITIONS_VIA",
        method_name="button_scrap",
        label_bouton="Scrap",
        groupe_requis=["stock.group_stock_multi_locations"],
    )
    res = button_execution_path(G, "Scrap", "stock.picking")
    assert "NOTE DE CONFIGURATION" in res.summary_text
    assert "stock.group_stock_multi_locations" in res.summary_text
    assert "paramètre: 'group_stock_multi_locations'" in res.summary_text


def test_predispatch_access_system_prompt_suffix_contains_synthesis_guidelines():
    from code_intelligence.agent.predispatch_access import dispatch_who_has_access_to
    G = nx.DiGraph()
    G.add_node("model:stock.quant", node_type="Model", name="stock.quant")
    G.add_node("model:stock.move.line", node_type="Model", name="stock.move.line")
    tool = RecordingTool()
    ctx = DispatchContext(
        G=G,
        concept=SimpleNamespace(
            is_resolved=True, resolved_models=["stock.quant", "stock.move.line"], resolved_modules=[],
        ),
        question="Un simple employe peut-il consulter les quantites en stock ?",
        tool_map={"who_has_access_to": tool},
        resolved_user_group_xmlids=[],
        trace_logger=FakeTraceLogger(),
        trace_id="test_guidelines",
        hop_cap=20,
    )
    dispatch_who_has_access_to(ctx)
    assert "[DETERMINISTIC PRE-DISPATCH -- ACCESS RIGHTS]" in ctx.system_prompt_suffix
    assert "IMPORTANT GUIDELINES FOR SYNTHESIS:" in ctx.system_prompt_suffix
    assert "Respect strictly the access verdicts from who_has_access_to" in ctx.system_prompt_suffix
    assert "explicitly cite its exact technical model name" in ctx.system_prompt_suffix


def test_xml_view_finder_detects_stock_multi_locations_technical_group(tmp_path):
    from code_intelligence.rules.xml_view_finder import _find_field_in_xml_views
    G = nx.DiGraph()
    G.add_node("model:stock.picking", node_type="Model", name="stock.picking")
    G.add_node("group:stock.group_stock_multi_locations", node_type="Group", name="Manage Multiple Stock Locations")
    G.add_node("field:res.config.settings.group_stock_multi_locations", node_type="Field", category_id="base.module_category_hidden")

    v_dir = tmp_path / "stock" / "views"
    v_dir.mkdir(parents=True)
    manifest = tmp_path / "stock" / "__manifest__.py"
    manifest.write_text("# stock manifest", encoding="utf-8")
    G.add_node("module:stock", node_type="Module", filepath=str(manifest))

    xml_file = v_dir / "stock_views.xml"
    xml_file.write_text(
        '<odoo><record id="view_picking_form" model="ir.ui.view">'
        '<field name="model">stock.picking</field>'
        '<field name="location_id" groups="!stock.group_stock_multi_locations"/>'
        '</record></odoo>',
        encoding="utf-8",
    )
    res = _find_field_in_xml_views(G, "stock.picking", "location_id")
    assert res is not None
    assert "NOTE DE CONFIGURATION" in res.summary_text
    assert "stock.group_stock_multi_locations" in res.summary_text


def test_relevance_budget_all_atomic_blocks_fit_under_budget():
    from code_intelligence.rules.relevance_budget import assemble_relevance_ranked_blocks
    blocks = [
        "[READ]: " + "g" * 3000,
        "[WRITE]: " + "g" * 3000,
        "[CREATE]: " + "g" * 3000,
        "[UNLINK]: " + "g" * 3000,
    ]
    res = assemble_relevance_ranked_blocks(blocks, 10000, question=None)
    assert "[READ]" in res
    assert "[WRITE]" in res
    assert "[CREATE]" in res
    assert "[UNLINK]" not in res
