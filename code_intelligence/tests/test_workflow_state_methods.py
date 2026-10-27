"""Methods that write the state field without a view button reach the graph and describe_workflow (section 1587)."""

from types import SimpleNamespace

import networkx as nx

from code_intelligence.extractor.python import extract_odoo_models_from_file
from code_intelligence.graph.nodes import add_workflow_nodes_and_edges
from code_intelligence.graph.version import GRAPH_SCHEMA_VERSION
from code_intelligence.rules.common import NO_WORKFLOW_TRANSITION_MARKER, QueryStatus
from code_intelligence.rules.workflow import describe_workflow

MODEL = "custom.purchase.request"

# Reproduces ext_purchase_request/models/purchase_request.py: a selection written by methods, no button in the view.
SOURCE = '''
class CustomPurchaseRequest(models.Model):
    _name = "custom.purchase.request"

    etat = fields.Selection(
        [("brouillon", "Brouillon"), ("a_valider", "A valider"), ("valide", "Valide"), ("refuse", "Refuse")],
        default="brouillon",
    )

    def action_soumettre(self):
        self.etat = "a_valider"

    def action_valider(self):
        for rec in self:
            rec.etat = "valide"

    def _reset(self):
        self.etat = "brouillon"
'''


def button(name, states="", label=""):
    return SimpleNamespace(name=name, string=label or name, states=states, invisible="", groups=[], context="")


def build_graph(tmp_path, buttons=()):
    path = tmp_path / "purchase_request.py"
    path.write_text(SOURCE, encoding="utf-8")
    registry = SimpleNamespace(models={MODEL: extract_odoo_models_from_file(path)})
    modules = {"m": SimpleNamespace(views=[SimpleNamespace(model=MODEL, buttons=list(buttons))])}
    graph = nx.DiGraph()
    graph.add_node(f"model:{MODEL}", node_type="Model")
    add_workflow_nodes_and_edges(graph, registry, modules)
    return graph


def test_graph_records_the_states_each_method_writes_on_the_model_node(tmp_path):
    graph = build_graph(tmp_path)
    node = graph.nodes[f"model:{MODEL}"]
    assert node["state_field"] == "etat"
    assert node["state_writes"] == [
        {"method_name": "action_soumettre", "states": ["a_valider"]},
        {"method_name": "action_valider", "states": ["valide"]},
        {"method_name": "_reset", "states": ["brouillon"]},
    ]
    assert not [1 for _, _, data in graph.edges(data=True) if data.get("edge_type") == "TRANSITIONS_VIA"]


def test_without_any_button_the_text_gives_the_states_and_the_writing_methods(tmp_path):
    result = describe_workflow(build_graph(tmp_path), MODEL)
    assert result.status == QueryStatus.EMPTY
    assert NO_WORKFLOW_TRANSITION_MARKER in result.summary_text
    assert "The state field 'etat' has the values: a_valider, brouillon, refuse, valide." in result.summary_text
    assert "`action_soumettre()` writes: a_valider" in result.summary_text
    assert "`action_valider()` writes: valide" in result.summary_text
    assert "_reset" not in result.summary_text
    assert "read the method before concluding" in result.summary_text
    assert [entry["method_name"] for entry in result.state_methods] == ["action_soumettre", "action_valider"]
    assert result.state_field == "etat"


def test_without_any_button_the_evidence_keeps_the_uncertain_fact_and_adds_the_written_states(tmp_path):
    result = describe_workflow(build_graph(tmp_path), MODEL)
    by_source = {evidence.source: evidence for evidence in result.evidence}
    assert by_source[f"workflow:{MODEL}"].confidence == "LOW"
    assert by_source[f"state_field:{MODEL}:etat"].value == "a_valider,brouillon,refuse,valide"
    assert by_source[f"state_write:{MODEL}:action_soumettre:a_valider"].confidence == "HIGH"
    assert by_source[f"state_write:{MODEL}:action_valider:valide"].value == "valide"
    assert not any("_reset" in source for source in by_source)
    assert len(result.evidence) == 4


def test_a_method_already_behind_a_button_transition_is_not_listed_twice(tmp_path):
    graph = build_graph(tmp_path, buttons=[button("action_soumettre", states="brouillon")])
    result = describe_workflow(graph, MODEL)
    assert result.status == QueryStatus.FOUND
    assert "[brouillon] -> [a_valider]" in result.summary_text
    assert [entry["method_name"] for entry in result.state_methods] == ["action_valider"]
    assert "`action_soumettre()` writes" not in result.summary_text
    assert "`action_valider()` writes: valide" in result.summary_text
    assert "has the values" not in result.summary_text


def test_an_older_graph_without_state_writes_lists_no_method_and_still_gives_the_states(tmp_path):
    graph = build_graph(tmp_path)
    del graph.nodes[f"model:{MODEL}"]["state_writes"]
    result = describe_workflow(graph, MODEL)
    assert result.state_methods == []
    assert "Methods that write" not in result.summary_text
    assert "has the values: a_valider, brouillon, refuse, valide" in result.summary_text


def test_the_schema_version_forces_a_rebuild_of_graphs_without_state_writes():
    assert GRAPH_SCHEMA_VERSION >= 21
