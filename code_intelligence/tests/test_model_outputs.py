"""Section 1420: reports and e-mail templates of a model are described, with French labels and the requester's verdict."""
import networkx as nx

from code_intelligence.graph.translations import TranslationEntry, attach_translations
from code_intelligence.rules.common import QueryStatus
from code_intelligence.rules.model_outputs import MAX_LISTED_OUTPUTS, describe_model_outputs
from code_intelligence.rules.navigation import describe_navigation_path

MODEL = "demo.order"


def _graph(report_count=0):
    graph = nx.DiGraph()
    graph.add_node(f"model:{MODEL}", node_type="Model")
    graph.add_node("group:demo.group_proforma", node_type="Group", name="Pro-forma")
    graph.add_node("report:demo.action_report_order", node_type="Report", xml_id="demo.action_report_order",
                   name="Quotation / Order", report_type="qweb-pdf", binding_model=MODEL)
    graph.add_node("report:demo.action_report_proforma", node_type="Report", xml_id="demo.action_report_proforma",
                   name="Pro-forma", report_type="qweb-html", binding_model="")
    for report in ("demo.action_report_order", "demo.action_report_proforma"):
        graph.add_edge(f"report:{report}", f"model:{MODEL}", edge_type="REPORTS_ON")
    graph.add_edge("report:demo.action_report_proforma", "group:demo.group_proforma", edge_type="APPLIES_TO_GROUP")
    graph.add_node("mail_template:demo.email_order", node_type="MailTemplate", xml_id="demo.email_order",
                   name="Send Quotation", template_description="Used by salespeople", active=True)
    graph.add_node("mail_template:demo.email_old", node_type="MailTemplate", xml_id="demo.email_old",
                   name="Old", active=False)
    for template in ("demo.email_order", "demo.email_old"):
        graph.add_edge(f"mail_template:{template}", f"model:{MODEL}", edge_type="TEMPLATE_FOR")
    graph.add_edge("mail_template:demo.email_order", "report:demo.action_report_order", edge_type="ATTACHES_REPORT")
    for index in range(report_count):
        node_id = f"report:demo.extra_{index}"
        graph.add_node(node_id, node_type="Report", xml_id=f"demo.extra_{index}", name=f"Extra {index}")
        graph.add_edge(node_id, f"model:{MODEL}", edge_type="REPORTS_ON")
    return graph


def test_reports_and_active_templates_are_described():
    outputs = describe_model_outputs(_graph(), MODEL, None)
    assert "'Quotation / Order' (PDF ; menu Imprimer ; sans restriction de groupe)" in outputs.summary
    assert "'Pro-forma' (HTML ; hors du menu Imprimer de ce modele ; groupes requis [demo.group_proforma" in outputs.summary
    assert "'Send Quotation' (rapport joint : Quotation / Order)" in outputs.summary
    assert "Old" not in outputs.summary
    assert "Used by salespeople" not in outputs.summary
    assert outputs.summary.index("Quotation / Order' (PDF") < outputs.summary.index("'Pro-forma'")


def test_verdict_depends_on_requester_groups():
    granted = describe_model_outputs(_graph(), MODEL, ["demo.group_proforma"])
    refused = describe_model_outputs(_graph(), MODEL, ["demo.group_warehouse"])
    unknown = describe_model_outputs(_graph(), MODEL, None)
    assert "NON disponible" not in granted.summary and "disponible pour le demandeur" in granted.summary
    assert "NON disponible pour le demandeur" in refused.summary
    assert "demandeur" not in unknown.summary
    assert any("is NOT available to this requester" in e.claim for e in refused.evidence)


def test_translated_label_is_listed_with_the_source_label():
    graph = _graph()
    graph.nodes["report:demo.action_report_order"]["business_labels"] = [{"label": "Devis / Commande"}]
    assert "'Quotation / Order / Devis / Commande'" in describe_model_outputs(graph, MODEL).summary


def test_listing_is_bounded():
    outputs = describe_model_outputs(_graph(report_count=10), MODEL)
    assert f"(+{12 - MAX_LISTED_OUTPUTS} autres)" in outputs.summary


def test_model_without_outputs_adds_nothing():
    graph = nx.DiGraph()
    graph.add_node(f"model:{MODEL}", node_type="Model")
    outputs = describe_model_outputs(graph, MODEL)
    assert (outputs.summary, outputs.evidence) == ("", [])


def test_navigation_describes_outputs_with_and_without_menu():
    without_menu = describe_navigation_path(_graph(), MODEL)
    assert without_menu.status == QueryStatus.EMPTY
    assert "Rapports imprimables" in without_menu.summary_text and without_menu.evidence

    graph = _graph()
    graph.add_node("menu:demo.menu_order", node_type="Menu", xml_id="demo.menu_order", name="Orders",
                   sequence=1, groups=[], action_domain="[]")
    graph.add_edge("menu:demo.menu_order", f"model:{MODEL}", edge_type="OPENS_MODEL")
    with_menu = describe_navigation_path(graph, MODEL)
    assert with_menu.status == QueryStatus.FOUND
    assert "Modeles d'e-mail" in with_menu.summary_text
    assert any("is declared on model" in e.claim for e in with_menu.evidence)


def test_report_and_template_names_are_translated():
    graph = _graph()
    entries = [
        TranslationEntry("Quotation / Order", "Devis / Commande", ("model:ir.actions.report,name:demo.action_report_order",), "fr", "demo"),
        TranslationEntry("Send Quotation", "Envoyer le devis", ("model:mail.template,name:email_order",), "fr", "demo"),
    ]
    assert attach_translations(graph, entries) == {"attached": 2, "unlinked": 0}
    assert graph.nodes["report:demo.action_report_order"]["business_labels"][0]["label"] == "Devis / Commande"
    assert graph.nodes["mail_template:demo.email_order"]["business_labels"][0]["entity_type"] == "mail_template"
