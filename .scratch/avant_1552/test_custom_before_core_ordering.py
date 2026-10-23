"""Code under a core addons path must not rank as custom because its file name contains "oca".

"oca" is a substring of "location", "local", "geolocalize"...: a core file such as
addons/stock/models/stock_location.py used to be treated as custom code and listed first.
"""

import networkx as nx
import pytest

from code_intelligence.rules.override_composer import _compose_compute_methods_overview
from code_intelligence.rules.xml_view_finder import _find_field_in_xml_views

CORE_FILE = "stock_location"

VIEW = (
    '<odoo><record id="{rid}" model="ir.ui.view"><field name="model">x.model</field>'
    '<field name="arch" type="xml"><form><field name="amount" readonly="1"/></form></field></record></odoo>'
)


def test_custom_override_is_listed_before_core_override():
    G = nx.DiGraph()
    G.add_node(
        "method:x.model._compute_total", node_type="Method", model="x.model", name="_compute_total",
        override_sites=[
            {"module": "aa_core", "filepath": f"/srv/odoo-17.0/addons/aa_core/models/{CORE_FILE}.py",
             "lineno": 1, "end_lineno": 2},
            {"module": "zz_custom", "filepath": "/srv/odoo_addons/zz_custom/models/model.py",
             "lineno": 3, "end_lineno": 4},
        ],
    )

    text = _compose_compute_methods_overview(G, "x.model").summary_text

    assert text.index("zz_custom") < text.index("aa_core")


def test_custom_view_is_chosen_before_core_view(tmp_path):
    if "oca" in str(tmp_path):
        pytest.skip("the temporary directory itself contains 'oca': the ordering cannot be isolated")
    G = nx.DiGraph()
    G.add_node("model:x.model", node_type="Model")
    G.add_node("field:x.model.amount", name="amount", label="Amount")
    G.add_edge("model:x.model", "field:x.model.amount", edge_type="HAS_FIELD")
    for root, module, view_file, record_id in (
        ("odoo-17.0/addons", "aa_core", f"{CORE_FILE}_views.xml", "a_core_view"),
        ("odoo_addons", "zz_custom", "views.xml", "z_custom_view"),
    ):
        views = tmp_path / root / module / "views"
        views.mkdir(parents=True)
        (views / view_file).write_text(VIEW.format(rid=record_id), encoding="utf-8")
        G.add_node(f"module:{module}", node_type="Module", filepath=str(views.parent / "__manifest__.py"))

    text = _find_field_in_xml_views(G, "x.model", "amount").summary_text

    assert "z_custom_view" in text
    assert "a_core_view" not in text
