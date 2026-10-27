"""The navigation answer lists the model's fields and indexed buttons, so a "how do I" reply is not written from memory (section 1589)."""

import networkx as nx

from code_intelligence.rules.common import QueryStatus
from code_intelligence.rules.navigation import (
    MAX_LISTED_BUTTONS,
    MAX_LISTED_FIELDS,
    ORPHAN_ACTION_MARKER,
    describe_navigation_path,
)

MODEL = "x.request"

FIELDS = [
    ("name", "Name", "Char", "Nom"),
    ("demandeur_id", "Demandeur Id", "Many2one", "Demandeur"),
    ("montant_estime", "Montant Estime", "Float", "Montant estime"),
]


def add_field(graph, name, label, fieldType, businessLabel):
    node = f"field:{MODEL}.{name}"
    graph.add_node(
        node, node_type="Field", name=name, model=MODEL, field_type=fieldType, label=label,
        label_source="generated", business_labels=[{"label": businessLabel}],
    )
    graph.add_edge(f"model:{MODEL}", node, edge_type="HAS_FIELD")


def add_button(graph, name, label):
    node = f"button:{MODEL}.{name}"
    graph.add_node(node, node_type="Button", name=name, label=label, model=MODEL, groups=[], invisible="")
    graph.add_edge(f"model:{MODEL}", node, edge_type="HAS_BUTTON", method_name=name, label_bouton=label, groupe_requis=[])


def build_graph(fields=FIELDS, buttons=(), withMenu=False, windowAction=True):
    graph = nx.DiGraph()
    graph.add_node(
        f"model:{MODEL}", node_type="Model",
        window_actions=[{"xml_id": "m.act", "name": "Demandes", "module": "m"}] if windowAction else [],
    )
    for field in fields:
        add_field(graph, *field)
    for name, label in buttons:
        add_button(graph, name, label)
    if withMenu:
        graph.add_node("menu:m.menu", node_type="Menu", name="Demandes", xml_id="m.menu", groups=[], sequence=1)
        graph.add_edge("menu:m.menu", f"model:{MODEL}", edge_type="OPENS_MODEL", via="window_action")
    return graph


def test_a_model_without_button_lists_its_fields_and_says_no_button_is_indexed():
    result = describe_navigation_path(build_graph(), MODEL)
    assert result.status == QueryStatus.EMPTY
    assert ORPHAN_ACTION_MARKER in result.summary_text
    assert "Champs du modele 'x.request' (3) : Nom (Char), Demandeur (Many2one), Montant estime (Float)." in result.summary_text
    assert "Demandeur Id" not in result.summary_text
    assert "Aucun bouton n'est declare dans les vues XML indexees de ce modele." in result.summary_text
    assert "ne couvre pas un bouton ajoute dynamiquement" in result.summary_text
    assert any("Form overview: Champs du modele" in step for step in result.execution_steps)


def test_the_form_overview_adds_sourced_evidence_with_the_right_confidence():
    result = describe_navigation_path(build_graph(), MODEL)
    by_source = {evidence.source: evidence for evidence in result.evidence}
    assert by_source[f"fields:{MODEL}"].confidence == "HIGH"
    assert by_source[f"fields:{MODEL}"].value == 3
    assert by_source[f"buttons:{MODEL}"].confidence == "MEDIUM"
    assert by_source[f"buttons:{MODEL}"].value == 0


def test_buttons_declared_in_the_views_are_listed_by_label():
    result = describe_navigation_path(build_graph(buttons=[("action_soumettre", "Soumettre"), ("action_valider", "Valider")]), MODEL)
    assert "Boutons declares dans les vues XML indexees : Soumettre, Valider." in result.summary_text
    assert "Aucun bouton" not in result.summary_text
    by_source = {evidence.source: evidence for evidence in result.evidence}
    assert by_source[f"buttons:{MODEL}"].confidence == "HIGH"
    assert by_source[f"buttons:{MODEL}"].value == 2


def test_lists_above_the_caps_are_replaced_by_a_count_without_evidence():
    manyFields = [(f"f{i}", f"F{i}", "Char", f"Champ {i}") for i in range(MAX_LISTED_FIELDS + 1)]
    manyButtons = [(f"b{i}", f"Bouton {i}") for i in range(MAX_LISTED_BUTTONS + 1)]
    result = describe_navigation_path(build_graph(fields=manyFields, buttons=manyButtons), MODEL)
    assert f"a {MAX_LISTED_FIELDS + 1} champs (liste omise)" in result.summary_text
    assert f"{MAX_LISTED_BUTTONS + 1} boutons declares dans les vues XML indexees (liste omise)" in result.summary_text
    assert "Champ 0" not in result.summary_text
    assert not any(evidence.source in (f"fields:{MODEL}", f"buttons:{MODEL}") for evidence in result.evidence)


def test_a_model_without_any_field_in_the_graph_gets_no_form_overview():
    result = describe_navigation_path(build_graph(fields=[]), MODEL)
    assert "Champs du modele" not in result.summary_text
    assert "Aucun bouton" not in result.summary_text
    assert len(result.evidence) == 1


def test_a_model_reached_by_a_menu_also_gets_the_form_overview():
    result = describe_navigation_path(build_graph(withMenu=True), MODEL)
    assert result.status == QueryStatus.FOUND
    assert "Champs du modele 'x.request' (3)" in result.summary_text
    assert any(step.startswith("5. Form overview:") for step in result.execution_steps)
    assert f"fields:{MODEL}" in {evidence.source for evidence in result.evidence}


def test_a_field_whose_label_is_not_generated_keeps_its_own_label():
    graph = build_graph(fields=[])
    graph.add_node(f"field:{MODEL}.ref", node_type="Field", name="ref", model=MODEL, field_type="Char",
                   label="Reference", label_source="explicit", business_labels=[{"label": "Reference"}])
    graph.add_edge(f"model:{MODEL}", f"field:{MODEL}.ref", edge_type="HAS_FIELD")
    assert "Reference (Char)" in describe_navigation_path(graph, MODEL).summary_text
