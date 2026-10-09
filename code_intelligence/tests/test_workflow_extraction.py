from types import SimpleNamespace

import networkx as nx

from code_intelligence.extractor.python import extract_odoo_models_from_file
from code_intelligence.graph.nodes import add_workflow_nodes_and_edges
from code_intelligence.graph.workflow_extraction import (
    origin_states,
    selection_values,
    split_on_or,
    written_states,
)

SOURCE = '''
STATES = [("draft", "Draft"), ("open", "Open"), ("done", "Done")]


class Doc(models.Model):
    _name = "x.doc"

    state = fields.Selection(selection=STATES)

    def action_open(self):
        self.write(self._open_values())

    def _open_values(self):
        return {"state": "open", "stamp": 1}

    def action_reset(self):
        docs = self.filtered(lambda doc: doc.state == "done")
        docs.write({"state": "draft"})

    def action_finish(self):
        for doc in self:
            doc.state = "done"

    def action_chain(self):
        self.action_finish()

    def action_foreign(self):
        self.env["other"].write({"state": "done"})

    def action_conditional(self):
        self.write({"state": "open"})
        self.filtered(lambda doc: doc.flag).write({"state": "done"})

    def action_ping(self):
        self.action_pong()

    def action_pong(self):
        self.action_ping()
        self.write({"state": "open"})

    def action_noop(self):
        self.locked = True


class DocExtension(models.Model):
    _inherit = "x.doc"

    state = fields.Selection(selection_add=[("archived", "Archived")])
'''


def declarations(tmp_path):
    path = tmp_path / "doc.py"
    path.write_text(SOURCE, encoding="utf-8")
    return extract_odoo_models_from_file(path)


def test_selection_is_resolved_from_a_module_constant_and_extensions(tmp_path):
    assert selection_values(declarations(tmp_path)) == ["draft", "open", "done", "archived"]


def test_selection_is_unknown_without_a_literal_list(tmp_path):
    path = tmp_path / "dynamic.py"
    path.write_text('class Doc(models.Model):\n    _name = "x.doc"\n    state = fields.Selection(selection=compute_states)\n')
    assert selection_values(extract_odoo_models_from_file(path)) is None


def test_written_states_follow_the_real_write_forms(tmp_path):
    decls = declarations(tmp_path)
    assert written_states(decls, "action_open") == ["open"]
    assert written_states(decls, "action_reset") == ["draft"]
    assert written_states(decls, "action_finish") == ["done"]
    assert written_states(decls, "action_chain") == ["done"]
    assert written_states(decls, "action_conditional") == ["open", "done"]


def test_writes_on_other_models_and_non_state_changes_are_not_transitions(tmp_path):
    decls = declarations(tmp_path)
    assert written_states(decls, "action_foreign") == []
    assert written_states(decls, "action_noop") == []
    assert written_states(decls, "missing") == []


def test_mutually_recursive_methods_terminate(tmp_path):
    assert written_states(declarations(tmp_path), "action_ping") == ["open"]


def test_origin_states_from_states_attribute_and_invisible_conditions():
    selection = ["draft", "sent", "done", "cancel"]
    assert origin_states("sent,draft", "", selection) == ["draft", "sent"]
    assert origin_states("", "state not in ('draft', 'sent')", selection) == ["draft", "sent"]
    assert origin_states("", "state != 'draft'", selection) == ["draft"]
    assert origin_states("", "state in ('done', 'cancel')", selection) == ["draft", "sent"]
    assert origin_states("", "state != 'draft' or locked", selection) == ["draft"]
    assert origin_states("", "(state == 'draft')", selection) == ["sent", "done", "cancel"]


def test_origin_states_are_unknown_rather_than_guessed():
    selection = ["draft", "done"]
    assert origin_states("", "", selection) is None
    assert origin_states("", "locked", selection) is None
    assert origin_states("", "state == compute()", selection) is None


def test_split_on_or_ignores_quoted_and_parenthesised_alternatives():
    assert split_on_or("a == 'x or y' or (b or c)") == ["a == 'x or y'", "(b or c)"]


def button(name, states="", invisible=""):
    return SimpleNamespace(name=name, states=states, invisible=invisible, string=name.title(), groups=[])


def test_workflow_graph_only_holds_proven_states_and_transitions(tmp_path):
    decls = declarations(tmp_path)
    buttons = [
        button("action_open", states="draft"),
        button("action_reset", invisible="state != 'done'"),
        button("action_conditional", states="open"),
        button("action_noop", states="open"),
        button("action_foreign"),
    ]
    registry = SimpleNamespace(models={"x.doc": decls})
    modules = {"m": SimpleNamespace(views=[SimpleNamespace(model="x.doc", buttons=buttons)])}
    graph = nx.DiGraph()

    add_workflow_nodes_and_edges(graph, registry, modules)

    states = {data["state_value"] for _, data in graph.nodes(data=True)}
    assert states == {"draft", "open", "done", "archived"}
    edges = {(u.split(".")[-1], v.split(".")[-1], d["method_name"], d["alternative"]) for u, v, d in graph.edges(data=True)}
    assert edges == {
        ("draft", "open", "action_open", False),
        ("done", "draft", "action_reset", False),
        ("open", "done", "action_conditional", True),
    }


def test_workflow_graph_preserves_distinct_buttons_for_the_same_transition(tmp_path):
    decls = declarations(tmp_path)
    decls[0].methods.append(SimpleNamespace(
        name="action_reopen", written_states=["open"], called_self_methods=[],
        returned_states=[], write_argument_methods=[],
    ))
    buttons = [button("action_open", states="draft"), button("action_reopen", states="draft")]
    registry = SimpleNamespace(models={"x.doc": decls})
    modules = {"m": SimpleNamespace(views=[SimpleNamespace(model="x.doc", buttons=buttons)])}
    graph = nx.DiGraph()

    add_workflow_nodes_and_edges(graph, registry, modules)

    assert graph.number_of_edges() == 1
    records = graph.edges["state:x.doc.draft", "state:x.doc.open"]["button_transitions"]
    assert [record["method_name"] for record in records] == ["action_open", "action_reopen"]
