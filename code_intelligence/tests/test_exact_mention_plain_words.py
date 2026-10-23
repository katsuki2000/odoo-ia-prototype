"""A technical name that is also an ordinary word is a literal mention only behind a marker.

Section 1480 (option A of 1479): `base`, `maintenance`, `project`... are plain words in a
question; a name containing "." or "_" (`sale.order`, `hr_holidays`) is not, and stays exact.
"""

import networkx as nx
import pytest

from code_intelligence.agent.resolution.matching import (
    _find_exact_technical_model_mentions,
    _find_exact_technical_module_mentions,
)
from code_intelligence.agent.resolution.exact_mention import resolve_exact_mention

PLAIN_NAMES = ["maintenance", "project", "calendar", "sale", "base"]


def _graph_with_modules(*names):
    graph = nx.DiGraph()
    for name in names:
        graph.add_node(f"module:{name}", node_type="Module", name=name)
    return graph


def _graph_with_models(*names):
    graph = nx.DiGraph()
    for name in names:
        graph.add_node(f"model:{name}", node_type="Model", name=name)
    return graph


def _maintenance_graph():
    graph = _graph_with_modules("maintenance")
    for model in ("maintenance.equipment", "maintenance.request"):
        graph.add_node(f"model:{model}", node_type="Model", name=model)
        graph.add_edge(f"model:{model}", "module:maintenance", edge_type="DEFINED_IN", role="declares")
    return graph


@pytest.mark.parametrize("name", PLAIN_NAMES)
def test_plain_word_module_without_marker_is_not_a_mention(name):
    graph = _graph_with_modules(name)

    assert _find_exact_technical_module_mentions(f"qui gere la {name} dans cette instance ?", graph) == []


@pytest.mark.parametrize("marker", ["module", "addon"])
@pytest.mark.parametrize("name", PLAIN_NAMES)
def test_plain_word_module_behind_a_marker_is_a_mention(marker, name):
    graph = _graph_with_modules(name)

    assert _find_exact_technical_module_mentions(f"que fait le {marker} {name} ?", graph) == [name]


def test_addon_marker_works_after_an_elision():
    graph = _graph_with_modules("maintenance")

    assert _find_exact_technical_module_mentions("que fait l'addon maintenance ?", graph) == ["maintenance"]


def test_application_is_not_a_marker():
    graph = _graph_with_modules("maintenance")

    assert _find_exact_technical_module_mentions("dans l'application maintenance, qui valide ?", graph) == []


@pytest.mark.parametrize("name", ["hr_holidays", "miro_credit_note_approval", "point_of_sale"])
def test_underscored_module_is_exact_without_marker(name):
    graph = _graph_with_modules(name)

    assert _find_exact_technical_module_mentions(f"qui valide dans {name} ?", graph) == [name]


@pytest.mark.parametrize("name", ["base", "website"])
def test_plain_word_model_without_marker_is_not_a_mention(name):
    graph = _graph_with_models(name)

    mentions = _find_exact_technical_model_mentions(
        f"quel groupe de {name} uniquement ?", graph, include_symbol_inference=False,
    )

    assert mentions == []


@pytest.mark.parametrize("marker", ["modele", "modèle", "model"])
@pytest.mark.parametrize("name", ["base", "website"])
def test_plain_word_model_behind_a_marker_is_a_mention(marker, name):
    graph = _graph_with_models(name)

    mentions = _find_exact_technical_model_mentions(
        f"que contient le {marker} {name} ?", graph, include_symbol_inference=False,
    )

    assert mentions == [name]


def test_dotted_model_is_exact_without_marker():
    graph = _graph_with_models("sale.order")

    assert _find_exact_technical_model_mentions(
        "que fait sale.order ?", graph, include_symbol_inference=False,
    ) == ["sale.order"]


def test_a_common_word_does_not_decide_a_maintenance_question():
    """MNT-Q2 / MNT-Q5 shape: 'maintenance' is the subject's vocabulary, not a module name."""
    result = resolve_exact_mention(
        "que se passe-t-il quand une demande de maintenance atteint l'etape done ?",
        "Que se passe-t-il quand une demande de maintenance atteint l'etape done ?",
        _maintenance_graph(),
    )

    assert result is None


def test_a_marked_module_name_decides_with_all_its_models():
    result = resolve_exact_mention(
        "dans le module maintenance, qui peut modifier une fiche ?",
        "Dans le module maintenance, qui peut modifier une fiche ?",
        _maintenance_graph(),
    )

    assert result is not None
    assert result.source_step == "exact_technical_mention"
    assert result.resolved_modules == ["maintenance"]
    assert set(result.resolved_models) == {"maintenance.equipment", "maintenance.request"}


def test_the_word_base_does_not_decide_a_group_question():
    """DDI-Q3 shape: 'groupe de base' is a sentence, not the model `base`."""
    graph = _graph_with_models("base", "custom.deep.document")

    result = resolve_exact_mention(
        "un utilisateur du groupe de base uniquement peut-il lire ?",
        "Un utilisateur du groupe de base uniquement peut-il lire ?",
        graph,
    )

    assert result is None


def test_a_marked_model_name_decides():
    result = resolve_exact_mention(
        "que contient le modele base ?",
        "Que contient le modele base ?",
        _graph_with_models("base", "custom.deep.document"),
    )

    assert result is not None
    assert result.resolved_models == ["base"]
