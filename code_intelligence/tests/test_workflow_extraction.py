from types import SimpleNamespace

import networkx as nx

from code_intelligence.extractor.python import extract_odoo_models_from_file
from code_intelligence.graph.nodes import add_workflow_nodes_and_edges
from code_intelligence.graph.state_field import lifecycle_field
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
    assert selection_values(declarations(tmp_path), "state") == ["draft", "open", "done", "archived"]


def test_selection_is_unknown_without_a_literal_list(tmp_path):
    path = tmp_path / "dynamic.py"
    path.write_text('class Doc(models.Model):\n    _name = "x.doc"\n    state = fields.Selection(selection=compute_states)\n')
    assert selection_values(extract_odoo_models_from_file(path), "state") is None


def test_written_states_follow_the_real_write_forms(tmp_path):
    decls = declarations(tmp_path)
    assert written_states(decls, "action_open", "state") == ["open"]
    assert written_states(decls, "action_reset", "state") == ["draft"]
    assert written_states(decls, "action_finish", "state") == ["done"]
    assert written_states(decls, "action_chain", "state") == ["done"]
    assert written_states(decls, "action_conditional", "state") == ["open", "done"]


def test_writes_on_other_models_and_non_state_changes_are_not_transitions(tmp_path):
    decls = declarations(tmp_path)
    assert written_states(decls, "action_foreign", "state") == []
    assert written_states(decls, "action_noop", "state") == []
    assert written_states(decls, "missing", "state") == []


def test_mutually_recursive_methods_terminate(tmp_path):
    assert written_states(declarations(tmp_path), "action_ping", "state") == ["open"]


def test_origin_states_from_states_attribute_and_invisible_conditions():
    selection = ["draft", "sent", "done", "cancel"]
    assert origin_states("sent,draft", "", selection, "state") == ["draft", "sent"]
    assert origin_states("", "state not in ('draft', 'sent')", selection, "state") == ["draft", "sent"]
    assert origin_states("", "state != 'draft'", selection, "state") == ["draft"]
    assert origin_states("", "state in ('done', 'cancel')", selection, "state") == ["draft", "sent"]
    assert origin_states("", "state != 'draft' or locked", selection, "state") == ["draft"]
    assert origin_states("", "(state == 'draft')", selection, "state") == ["sent", "done", "cancel"]


def test_origin_states_are_unknown_rather_than_guessed():
    selection = ["draft", "done"]
    assert origin_states("", "", selection, "state") is None
    assert origin_states("", "locked", selection, "state") is None
    assert origin_states("", "state == compute()", selection, "state") is None


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
        name="action_reopen", written_values={"state": ["open"]}, called_self_methods=[],
        returned_values={}, write_argument_methods=[],
    ))
    buttons = [button("action_open", states="draft"), button("action_reopen", states="draft")]
    registry = SimpleNamespace(models={"x.doc": decls})
    modules = {"m": SimpleNamespace(views=[SimpleNamespace(model="x.doc", buttons=buttons)])}
    graph = nx.DiGraph()

    add_workflow_nodes_and_edges(graph, registry, modules)

    assert graph.number_of_edges() == 1
    records = graph.edges["state:x.doc.draft", "state:x.doc.open"]["button_transitions"]
    assert [record["method_name"] for record in records] == ["action_open", "action_reopen"]


CUSTOM_SOURCE = '''
from odoo import models, fields


class AssetLoan(models.Model):
    _name = "x.loan"

    priority = fields.Selection([("low", "Low"), ("high", "High")])
    level = fields.Selection([("a", "A"), ("b", "B"), ("c", "C")], compute="_compute_level")
    etat = fields.Selection([("brouillon", "Brouillon"), ("en_cours", "En cours"), ("restitue", "Restitue")])

    def _compute_level(self):
        for rec in self:
            rec.level = "a"
        for rec in self:
            rec.level = "b"

    def action_demarrer(self):
        for rec in self:
            rec.etat = "en_cours"
            rec.priority = "high"

    def action_restituer(self):
        self.write({"etat": "restitue"})
'''


def custom_declarations(tmp_path):
    path = tmp_path / "loan.py"
    path.write_text(CUSTOM_SOURCE, encoding="utf-8")
    return extract_odoo_models_from_file(path)


def test_lifecycle_field_is_found_without_the_name_state(tmp_path):
    decls = custom_declarations(tmp_path)
    assert lifecycle_field(decls) == "etat"
    assert selection_values(decls, "etat") == ["brouillon", "en_cours", "restitue"]
    assert written_states(decls, "action_demarrer", "etat") == ["en_cours"]
    assert written_states(decls, "action_restituer", "etat") == ["restitue"]


def test_computed_and_less_written_selections_are_not_the_lifecycle(tmp_path):
    decls = custom_declarations(tmp_path)
    assert lifecycle_field(decls) != "level"
    assert lifecycle_field(decls) != "priority"


def test_model_without_a_written_selection_has_no_lifecycle(tmp_path):
    path = tmp_path / "plain.py"
    path.write_text("from odoo import models, fields\n\nclass P(models.Model):\n    _name = 'x.plain'\n    kind = fields.Selection([('a', 'A')])\n", encoding="utf-8")
    assert lifecycle_field(extract_odoo_models_from_file(path)) is None


def test_workflow_graph_uses_the_detected_field_and_records_it(tmp_path):
    decls = custom_declarations(tmp_path)
    registry = SimpleNamespace(models={"x.loan": decls})
    modules = {"m": SimpleNamespace(views=[SimpleNamespace(model="x.loan", buttons=[button("action_demarrer", invisible="etat != 'brouillon'")])])}
    graph = nx.DiGraph()
    graph.add_node("model:x.loan", node_type="Model")

    add_workflow_nodes_and_edges(graph, registry, modules)

    assert graph.nodes["model:x.loan"]["state_field"] == "etat"
    assert {data["state_value"] for _, data in graph.nodes(data=True) if data.get("node_type") == "WorkflowState"} == {"brouillon", "en_cours", "restitue"}
    assert [(u.split(".")[-1], v.split(".")[-1]) for u, v in graph.edges] == [("brouillon", "en_cours")]


def test_state_declared_by_the_model_is_the_lifecycle_even_when_another_selection_is_written_more(tmp_path):
    path = tmp_path / "both.py"
    path.write_text(
        "from odoo import models, fields\n\nclass B(models.Model):\n    _name = 'x.both'\n"
        "    state = fields.Selection([('a', 'A'), ('b', 'B')], compute='_c', store=True)\n"
        "    stage = fields.Selection([('p', 'P'), ('q', 'Q'), ('r', 'R')])\n\n"
        "    def action_go(self):\n        self.stage = 'p'\n        self.stage = 'q'\n",
        encoding="utf-8",
    )
    assert lifecycle_field(extract_odoo_models_from_file(path)) == "state"


def test_onchange_writes_do_not_make_a_lifecycle_field(tmp_path):
    path = tmp_path / "cfg.py"
    path.write_text(
        "from odoo import api, models, fields\n\nclass C(models.Model):\n    _name = 'x.cfg'\n"
        "    mode = fields.Selection([('a', 'A'), ('b', 'B')])\n\n"
        "    @api.onchange('mode')\n    def _onchange_mode(self):\n        self.mode = 'a'\n",
        encoding="utf-8",
    )
    assert lifecycle_field(extract_odoo_models_from_file(path)) is None
