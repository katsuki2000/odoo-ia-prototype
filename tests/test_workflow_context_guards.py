"""Workflow edges: a state write guarded by a context flag the button never sets is not a transition."""

import ast

import networkx as nx

from code_intelligence.extractor.python import OdooClassVisitor
from code_intelligence.graph.workflow_extraction import context_flags_of_text, written_states
from code_intelligence.rules.workflow import describe_workflow

SOURCE = '''
from odoo import models


class Order(models.Model):
    _name = "x.order"

    def message_post(self, **kwargs):
        if self.env.context.get("mark_sent"):
            self.filtered(lambda o: o.state == "draft").write({"state": "sent"})
        return super().message_post(**kwargs)

    def action_update_prices(self):
        self.message_post(body="recomputed")

    def action_send(self):
        self.with_context(mark_sent=True).message_post(body="sent")

    def action_confirm(self):
        self.write({"state": "sale"})

    def action_with_default(self):
        if self.env.context.get("auto", True):
            self.write({"state": "done"})

    def action_mixed_guard(self):
        if self.env.context.get("force") and self.amount > 0:
            self.write({"state": "locked"})

    def action_unreadable_guard(self):
        if self.amount > 0 and self.is_ready():
            self.write({"state": "ready"})
'''


def declarations():
    visitor = OdooClassVisitor()
    visitor.visit(ast.parse(SOURCE))
    return visitor.declarations


def targets(method, flags=None):
    return written_states(declarations(), method, "state", context_flags=flags)


def test_guarded_write_reached_through_an_unflagged_call_is_dropped():
    assert targets("action_update_prices", set()) == []


def test_flag_set_by_with_context_on_the_call_keeps_the_write():
    assert targets("action_send", set()) == ["sent"]


def test_flag_set_by_the_view_button_keeps_the_write():
    assert targets("action_update_prices", {"mark_sent"}) == ["sent"]


def test_unreadable_view_context_keeps_everything():
    assert targets("action_update_prices", context_flags_of_text("{**base}")) == ["sent"]
    assert targets("action_update_prices", context_flags_of_text("dict(a=1)")) == ["sent"]
    assert context_flags_of_text("{'a': active_id}") == {"a"}
    assert context_flags_of_text("") == set()
    assert context_flags_of_text("{'mark_sent': True}") == {"mark_sent"}


def test_direct_unguarded_write_is_unchanged():
    assert targets("action_confirm", set()) == ["sale"]


def test_get_with_truthy_default_is_not_a_guard():
    assert targets("action_with_default", set()) == ["done"]


def test_and_with_a_context_read_still_requires_the_flag():
    assert targets("action_mixed_guard", set()) == []
    assert targets("action_mixed_guard", {"force"}) == ["locked"]


def test_condition_without_context_read_is_not_a_guard():
    assert targets("action_unreadable_guard", set()) == ["ready"]


def test_no_flag_filter_keeps_current_behaviour():
    assert targets("action_update_prices", None) == ["sent"]


def _workflow_graph(groups):
    G = nx.DiGraph()
    G.add_node("model:x.order")
    for state in ("draft", "sale"):
        G.add_node(f"state:x.order.{state}", node_type="WorkflowState", model="x.order", state_value=state)
    G.add_edge("state:x.order.draft", "state:x.order.sale", edge_type="TRANSITIONS_VIA", button_transitions=[
        {"method_name": "action_confirm", "label_bouton": "Confirm", "groupe_requis": groups, "alternative": False}])
    return G


def test_workflow_text_keeps_the_role_token_and_explains_it():
    text = describe_workflow(_workflow_graph([]), "x.order").summary_text
    assert "Role: [All Users]" in text
    assert "Note: 'Role: [All Users]' means no group is declared" in text


def test_workflow_text_has_no_note_when_every_button_declares_a_group():
    text = describe_workflow(_workflow_graph(["x.group_manager"]), "x.order").summary_text
    assert "Note:" not in text and "All Users" not in text
