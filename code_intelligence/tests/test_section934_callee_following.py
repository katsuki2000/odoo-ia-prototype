"""
todo/contexte.txt section 934: a deterministic dispatcher must read the methods a
button body uses as conditions, not only its button_* calls. SAL-Q2 answered from
memory because action_confirm stops at so._should_be_locked(), whose body holds
the real condition (create_uid.has_group of a settings-activated group).
"""

import pytest

from code_intelligence.rules.source_callees import (
    extract_followable_callees,
    extract_has_group_literals,
)
from code_intelligence.rules.technical_groups import technical_groups_among

_ACTION_CONFIRM = '''
    def action_confirm(self):
        if not all(order._can_be_confirmed() for order in self):
            raise UserError("state")
        self.write(self._prepare_confirmation_values())
        self.with_context(context)._action_confirm()
        self.filtered(lambda so: so._should_be_locked()).action_lock()
        if self.env.context.get('send_email'):
            self._send_order_confirmation_mail()
        return True
'''

_BUTTON_CONFIRM = '''
    def button_confirm(self):
        for order in self:
            if order.state not in ['draft', 'sent']:
                continue
            if order._approval_allowed():
                order.button_approve()
            else:
                order.write({'state': 'to approve'})
'''


def test_conditions_come_before_delegated_steps():
    assert extract_followable_callees(_ACTION_CONFIRM, "action_confirm") == [
        "_can_be_confirmed", "_should_be_locked",
        "_prepare_confirmation_values", "_action_confirm", "action_lock", "_send_order_confirmation_mail",
    ]


def test_button_calls_come_before_conditions():
    assert extract_followable_callees(_BUTTON_CONFIRM, "button_confirm") == [
        "button_approve", "_approval_allowed",
    ]


def test_plain_statement_calls_to_same_model_are_followed_but_not_framework_methods():
    source = "def action_done(self):\n    self.write({})\n    self._notify()\n"
    assert extract_followable_callees(source, "action_done") == ["_notify"]


def test_calls_on_related_fields_are_not_delegated_steps():
    source = "def action_done(self):\n    self.partner_id.notify()\n    self.order_line._check()\n"
    assert extract_followable_callees(source, "action_done") == []


def test_unparsable_source_yields_nothing():
    assert extract_followable_callees("def broken(:", "broken") == []


def test_has_group_literals_extracted():
    source = "def _should_be_locked(self):\n    return self.create_uid.has_group('sale.group_auto_done_setting')\n"
    assert extract_has_group_literals(source) == ["sale.group_auto_done_setting"]


def test_technical_group_detected_from_graph_node():
    import networkx as nx
    G = nx.DiGraph()
    G.add_node("group:shop.group_flag", group_type="technical", setting_field="group_flag", name="Flag Option")
    G.add_node("group:shop.group_role", group_type="role")
    assert technical_groups_among(G, ["shop.group_flag", "shop.group_role", "shop.unknown"]) == [
        ("shop.group_flag", "group_flag", "Flag Option"),
    ]


def test_technical_group_note_carries_exact_display_name():
    from code_intelligence.rules.technical_groups import TechnicalGroup, format_technical_group_note
    note = format_technical_group_note([TechnicalGroup("sale.group_auto_done_setting", "group_auto_done_setting", "Lock Confirmed Sales")])
    assert "'Lock Confirmed Sales'" in note
    assert "sale.group_auto_done_setting" in note


@pytest.fixture(scope="module")
def real_graph():
    from code_intelligence.graph.loader import get_code_intelligence_graph
    return get_code_intelligence_graph()


def test_sal_q2_reads_should_be_locked_with_technical_group_note(real_graph):
    from types import SimpleNamespace
    from code_intelligence.agent.context import DispatchContext
    from code_intelligence.agent.predispatch_structure import dispatch_button_execution_path
    from code_intelligence.agent.tool_helpers import set_graph_ref
    from code_intelligence.agent.tools import ALL_CI_TOOLS

    class FakeTraceLogger:
        def log_hop(self, *args, **kwargs):
            pass

    set_graph_ref(real_graph)
    ctx = DispatchContext(
        G=real_graph,
        concept=SimpleNamespace(is_resolved=True, resolved_models=["sale.order"], resolved_modules=[]),
        question=(
            "Que se passe-t-il exactement quand on confirme une commande de vente "
            "(action_confirm), et dans quel cas est-elle automatiquement verrouillee (locked) ?"
        ),
        tool_map={t.name: t for t in ALL_CI_TOOLS},
        resolved_user_group_xmlids=[],
        trace_logger=FakeTraceLogger(),
        trace_id="test",
        hop_cap=20,
    )
    dispatch_button_execution_path(ctx)

    locked_obs = next(o for o in ctx.tool_observations if "def _should_be_locked" in o)
    assert "create_uid.has_group('sale.group_auto_done_setting')" in locked_obs
    assert "group_auto_done_setting" in locked_obs.split("NOTE DE CONFIGURATION")[1]
    assert "CALLED METHODS" in ctx.system_prompt_suffix

    tax_hook_obs = next(o for o in ctx.tool_observations if "def validate_taxes_on_sales_order" in o)
    assert "return True" in tax_hook_obs
