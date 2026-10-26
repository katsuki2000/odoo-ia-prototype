import networkx as nx

from code_intelligence.graph.runtime_translations import read_runtime_translations
from code_intelligence.graph.translations import attach_translations, parse_po
from code_intelligence.rules.group_resolver import get_group_display_name, resolve_group_identifier


def test_static_group_translation_uses_french_po_label(tmp_path):
    po_path = tmp_path / "fr.po"
    po_path.write_text(
        '#: model:res.groups,name:purchase.group_purchase_manager\n'
        'msgid "Purchase Manager"\n'
        'msgstr "Responsable des achats"\n',
        encoding="utf-8",
    )
    graph = nx.DiGraph()
    graph.add_node(
        "group:purchase.group_purchase_manager",
        node_type="Group",
        xml_id="purchase.group_purchase_manager",
        name="Purchase Manager",
    )

    summary = attach_translations(graph, parse_po(po_path, "purchase"))

    assert summary == {"attached": 1, "unlinked": 0}
    assert get_group_display_name(graph, "purchase.group_purchase_manager") == "Responsable des achats"


def test_group_without_translation_uses_source_name():
    graph = nx.DiGraph()
    graph.add_node(
        "group:custom_access.group_custom_user",
        node_type="Group",
        xml_id="custom_access.group_custom_user",
        name="Custom User",
    )

    assert get_group_display_name(graph, "custom_access.group_custom_user") == "Custom User"


def test_duplicate_group_labels_include_the_translated_application_name(tmp_path):
    purchase_po = tmp_path / "purchase_fr.po"
    purchase_po.write_text(
        '#: model:res.groups,name:group_manager\n'
        'msgid "Manager"\n'
        'msgstr "Responsable"\n\n'
        '#: model:ir.module.category,name:module_category_purchase\n'
        'msgid "Purchase"\n'
        'msgstr "Achats"\n',
        encoding="utf-8",
    )
    sale_po = tmp_path / "sale_fr.po"
    sale_po.write_text(
        '#: model:res.groups,name:group_manager\n'
        'msgid "Manager"\n'
        'msgstr "Responsable"\n\n'
        '#: model:ir.module.category,name:module_category_sales\n'
        'msgid "Sales"\n'
        'msgstr "Ventes"\n',
        encoding="utf-8",
    )
    graph = nx.DiGraph()
    graph.add_node(
        "group:purchase.group_manager",
        node_type="Group",
        xml_id="purchase.group_manager",
        name="Manager",
        category_id="purchase.module_category_purchase",
    )
    graph.add_node(
        "group:sale.group_manager",
        node_type="Group",
        xml_id="sale.group_manager",
        name="Manager",
        category_id="sale.module_category_sales",
    )

    summary = attach_translations(graph, parse_po(purchase_po, "purchase"))
    summary_sale = attach_translations(graph, parse_po(sale_po, "sale"))

    assert summary == {"attached": 2, "unlinked": 0}
    assert summary_sale == {"attached": 2, "unlinked": 0}
    assert get_group_display_name(graph, "purchase.group_manager") == "Achats : Responsable"
    assert get_group_display_name(graph, "sale.group_manager") == "Ventes : Responsable"


class GroupRuntimeConnector:
    def __init__(self):
        self.calls = []

    def search_read(self, **kwargs):
        self.calls.append(kwargs)
        model = kwargs["model"]
        if model == "ir.model":
            return [{"model": "custom.ticket", "name": "Ticket"}]
        if model == "ir.model.fields":
            return [{"model": "custom.ticket", "name": "state", "field_description": "State"}]
        if model == "res.groups":
            return [{"id": 17, "name": "Responsable", "category_id": [31, "Achats"]}]
        if model == "ir.module.category":
            return [{"id": 31, "name": "Achats"}]
        if model == "ir.model.data":
            model_name = kwargs["domain"][0][2]
            if model_name == "res.groups":
                return [{"module": "custom_access", "name": "group_manager", "res_id": 17}]
            return [{"module": "custom_access", "name": "module_category_access", "res_id": 31}]
        return []


def test_runtime_group_labels_are_read_for_each_active_language_and_resolved_by_xmlid():
    connector = GroupRuntimeConnector()

    labels, summary = read_runtime_translations(
        connector,
        7,
        ["fr"],
        ["en_US", "fr_FR"],
    )

    group_label = next(label for label in labels if label["entity_type"] == "group")
    assert summary["queried_languages"] == ["fr_FR"]
    assert summary["group_records"] == 1
    assert group_label == {
        "node_id": "group:custom_access.group_manager",
        "label": "Responsable",
        "language": "fr_FR",
        "entity_type": "group",
        "reference": "res.groups:custom_access.group_manager",
    }
    assert all(call["context"] == {"lang": "fr_FR"} for call in connector.calls)


def _translated_groups(*groups):
    graph = nx.DiGraph()
    for xml_id, name, french in groups:
        graph.add_node(
            f"group:{xml_id}",
            node_type="Group",
            xml_id=xml_id,
            name=name,
            business_labels=[{"label": french, "language": "fr_FR"}],
        )
    return graph


def test_group_resolves_from_its_source_name_and_from_its_translation():
    graph = _translated_groups(("account.group_account_manager", "Billing Administrator", "Administrateur de facturation"))
    candidates = ["account.group_account_manager"]

    assert resolve_group_identifier(graph, "Billing Administrator", candidates) == "account.group_account_manager"
    assert resolve_group_identifier(graph, "administrateur de facturation", candidates) == "account.group_account_manager"
    assert get_group_display_name(graph, "account.group_account_manager") == "Administrateur de facturation"


def test_exact_group_name_beats_a_shorter_candidate_listed_first():
    graph = _translated_groups(
        ("account.group_account_invoice", "Billing", "Facturation"),
        ("account.group_account_manager", "Billing Administrator", "Administrateur de facturation"),
    )
    candidates = ["account.group_account_invoice", "account.group_account_manager"]

    assert resolve_group_identifier(graph, "Billing Administrator", candidates) == "account.group_account_manager"
    assert resolve_group_identifier(graph, "Billing", candidates) == "account.group_account_invoice"


def test_unrelated_group_name_resolves_nothing():
    graph = _translated_groups(("account.group_account_manager", "Billing Administrator", "Administrateur de facturation"))

    assert resolve_group_identifier(graph, "Stock Manager", ["account.group_account_manager"]) is None
