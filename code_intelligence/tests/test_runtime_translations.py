from code_intelligence.graph.runtime_translations import read_runtime_translations
from code_intelligence.graph.translations import attach_runtime_translations
from erp_data.odoo_connector import OdooConnectorError


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
    assert [call["context"] for call in connector.calls] == [{"lang": "fr_FR"}] * 4


def test_runtime_labels_skip_a_requested_language_that_is_not_active():
    labels, summary = read_runtime_translations(FakeConnector(), 7, ["fr"], ["en_US"])

    assert labels == []
    assert summary["queried_languages"] == []


def test_runtime_translation_connector_failure_is_reported_by_language(caplog):
    class FailingConnector(FakeConnector):
        def search_read(self, **kwargs):
            if kwargs["model"] == "res.groups":
                raise OdooConnectorError("Model res.groups is not whitelisted")
            return super().search_read(**kwargs)

    labels, summary = read_runtime_translations(
        FailingConnector(),
        7,
        ["fr"],
        ["fr_FR"],
    )

    assert labels == []
    assert summary["failed_languages"] == ["fr_FR"]
    assert "Could not read runtime translations for language fr_FR" in caplog.text


def test_runtime_translation_does_not_hide_unexpected_errors():
    class BrokenConnector(FakeConnector):
        def search_read(self, **kwargs):
            if kwargs["model"] == "res.groups":
                raise ValueError("Unexpected malformed runtime data")
            return super().search_read(**kwargs)

    import pytest

    with pytest.raises(ValueError, match="Unexpected malformed runtime data"):
        read_runtime_translations(BrokenConnector(), 7, ["fr"], ["fr_FR"])


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
