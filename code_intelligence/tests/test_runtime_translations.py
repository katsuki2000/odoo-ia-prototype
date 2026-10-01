from code_intelligence.graph.runtime_translations import read_runtime_translations
from code_intelligence.graph.translations import attach_runtime_translations


class FakeConnector:
    def __init__(self):
        self.calls = []

    def search_read(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["model"] == "ir.model":
            return [{"model": "custom.ticket", "name": "Ticket client"}]
        return [{
            "model": "custom.ticket",
            "name": "priority",
            "field_description": "Priorite",
        }]


def test_runtime_labels_use_the_matching_active_language_and_graph_nodes():
    connector = FakeConnector()

    labels, summary = read_runtime_translations(
        connector,
        7,
        ["fr"],
        ["en_US", "fr_FR"],
    )

    assert summary["queried_languages"] == ["fr_FR"]
    assert labels == [
        {
            "node_id": "model:custom.ticket",
            "label": "Ticket client",
            "language": "fr_FR",
            "entity_type": "model",
            "reference": "ir.model:custom.ticket",
        },
        {
            "node_id": "field:custom.ticket.priority",
            "label": "Priorite",
            "language": "fr_FR",
            "entity_type": "field",
            "reference": "ir.model.fields:custom.ticket.priority",
        },
    ]
    assert [call["context"] for call in connector.calls] == [{"lang": "fr_FR"}] * 2


def test_runtime_labels_skip_a_requested_language_that_is_not_active():
    labels, summary = read_runtime_translations(FakeConnector(), 7, ["fr"], ["en_US"])

    assert labels == []
    assert summary["queried_languages"] == []


def test_runtime_attachment_deduplicates_repeated_records():
    import networkx as nx

    graph = nx.DiGraph()
    graph.add_node("model:custom.ticket", node_type="Model")
    record = {
        "node_id": "model:custom.ticket",
        "label": "Ticket client",
        "language": "fr_FR",
        "entity_type": "model",
        "reference": "ir.model:custom.ticket",
    }

    assert attach_runtime_translations(graph, [record, record]) == {"attached": 1, "unlinked": 0}
