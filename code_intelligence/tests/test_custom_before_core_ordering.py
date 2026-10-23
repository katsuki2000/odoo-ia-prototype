"""Custom code is ranked before core code, with core defined by the configured core addons roots.

A path substring such as "/addons/" or "oca" is not a reliable marker: custom code may live under a
directory named `addons`, and core file names may contain "oca" ("stock_location").
"""

import networkx as nx
import pytest

from code_intelligence.rules.override_composer import _compose_compute_methods_overview
from code_intelligence.rules.xml_view_finder import _find_field_in_xml_views
from code_intelligence.utils import is_core_source

VIEW = (
    '<odoo><record id="{rid}" model="ir.ui.view"><field name="model">x.model</field>'
    '<field name="arch" type="xml"><form><field name="amount" readonly="1"/></form></field></record></odoo>'
)


@pytest.fixture
def roots(tmp_path, monkeypatch):
    core = tmp_path / "odoo-17.0" / "addons"
    framework = tmp_path / "odoo-17.0" / "odoo" / "addons"
    custom = tmp_path / "srv" / "addons"
    monkeypatch.setattr("config.settings.CORE_ADDONS_PATH", str(core))
    monkeypatch.setattr("config.settings.CORE_FRAMEWORK_ADDONS_PATH", str(framework))
    return core, framework, custom


def test_is_core_source_follows_the_configured_roots(roots):
    core, framework, custom = roots
    assert is_core_source(core / "stock" / "models" / "stock_location.py")
    assert is_core_source(str(framework / "base" / "models" / "res_users.py"))
    assert not is_core_source(custom / "mod" / "models" / "model.py")
    assert not is_core_source(core.parent / "addons_extra" / "mod" / "model.py")


def test_custom_override_is_listed_before_core_override(roots):
    core, _, custom = roots
    G = nx.DiGraph()
    G.add_node(
        "method:x.model._compute_total", node_type="Method", model="x.model", name="_compute_total",
        override_sites=[
            {"module": "aa_core", "filepath": str(core / "aa_core" / "models" / "model.py"),
             "lineno": 1, "end_lineno": 2},
            {"module": "zz_custom", "filepath": str(custom / "zz_custom" / "models" / "model.py"),
             "lineno": 3, "end_lineno": 4},
        ],
    )

    text = _compose_compute_methods_overview(G, "x.model").summary_text

    assert text.index("zz_custom") < text.index("aa_core")


def test_custom_view_is_chosen_before_core_view(roots):
    core, _, custom = roots
    G = nx.DiGraph()
    G.add_node("model:x.model", node_type="Model")
    G.add_node("field:x.model.amount", name="amount", label="Amount")
    G.add_edge("model:x.model", "field:x.model.amount", edge_type="HAS_FIELD")
    for root, module, record_id in ((core, "aa_core", "a_core_view"), (custom, "zz_custom", "z_custom_view")):
        views = root / module / "views"
        views.mkdir(parents=True)
        (views / "views.xml").write_text(VIEW.format(rid=record_id), encoding="utf-8")
        G.add_node(f"module:{module}", node_type="Module", filepath=str(views.parent / "__manifest__.py"))

    text = _find_field_in_xml_views(G, "x.model", "amount").summary_text

    assert "z_custom_view" in text
    assert "a_core_view" not in text
