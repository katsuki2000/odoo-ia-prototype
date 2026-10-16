import ast
import xml.etree.ElementTree as ET

from code_intelligence.extractor.http_routes import parse_http_routes
from code_intelligence.extractor.python import extract_odoo_models_from_file
from code_intelligence.extractor.xml import parse_actions_from_xml


def test_python_extractors_accept_the_same_parsed_ast(tmp_path):
    path = tmp_path / "models.py"
    source = """
from odoo import models, fields
class Example(models.Model):
    _name = "example.record"
    name = fields.Char()
    @http.route("/example", auth="public")
    def route_example(self):
        return True
"""
    tree = ast.parse(source, filename=str(path))

    models = extract_odoo_models_from_file(path, source=source, tree=tree)
    routes = parse_http_routes(path, source=source, tree=tree)

    assert [model.name for model in models] == ["example.record"]
    assert [(route.controller, route.method_name, route.paths) for route in routes] == [
        ("Example", "route_example", ["/example"])
    ]


def test_xml_extractor_accepts_a_preparsed_document(monkeypatch, tmp_path):
    path = tmp_path / "actions.xml"
    root = ET.fromstring(
        '<odoo><record id="open_example" model="ir.actions.act_window">'
        '<field name="name">Example</field><field name="res_model">example.record</field>'
        '</record></odoo>'
    )
    monkeypatch.setattr(
        "code_intelligence.extractor.xml.parse_xml_root",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("XML parsed again")),
    )

    actions = parse_actions_from_xml(path, parsed_xml=("<odoo/>", root))

    assert len(actions) == 1
    assert actions[0].xml_id == "open_example"
    assert actions[0].res_model == "example.record"
