import pytest

from code_intelligence.extractor.csv import ACCESS_CONTROL_CSV_NAME, OdooAccessEntry
from code_intelligence.graph.builder import OdooGraphBuilder
from code_intelligence.graph.loader import _load_module
from code_intelligence.graph.nodes import ParsedModule
from code_intelligence.graph.symbols import build_module_symbol_registry
from code_intelligence.utils import qualify_xml_id


ACL_HEADER = "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"


def _write_module(root, name, files):
    module_dir = root / name
    module_dir.mkdir()
    (module_dir / "__manifest__.py").write_text(
        "{'name': '%s', 'depends': ['base']}" % name, encoding="utf-8"
    )
    for relative, content in files.items():
        target = module_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return module_dir


def _build_graph(module_name, entries):
    modules = {module_name: ParsedModule(manifest=None, acl_entries=entries)}
    registry = build_module_symbol_registry(modules)
    return OdooGraphBuilder(registry, modules).build_graph()


def _entry(xml_id, group_id):
    return OdooAccessEntry(
        xml_id=xml_id,
        filepath="",
        lineno=2,
        name=xml_id,
        model_id="model_sale_order",
        group_id=group_id,
        all_authenticated=group_id is None,
        perm_read=True,
    )


def _group_targets(graph, acl_node_id):
    return {
        target
        for _, target, data in graph.out_edges(acl_node_id, data=True)
        if data.get("edge_type") == "APPLIES_TO_GROUP"
    }


@pytest.mark.parametrize(
    "xml_id, module, expected",
    [
        ("group_user", "sale", "sale.group_user"),
        ("base.group_user", "sale", "base.group_user"),
    ],
)
def test_qualify_xml_id(xml_id, module, expected):
    assert qualify_xml_id(xml_id, module) == expected


def test_loader_reads_only_the_access_control_csv(tmp_path):
    _write_module(
        tmp_path,
        "demo_module",
        {
            f"security/{ACCESS_CONTROL_CSV_NAME}": ACL_HEADER
            + "access_demo,access.demo,model_demo_model,base.group_user,1,0,0,0\n",
            "data/res.lang.csv": "id,name,code\nlang_demo,Demo,de_DE\n",
            "data/res.country.state.csv": "id,name,code\nstate_demo,Demo,DM\n",
        },
    )

    _, parsed = _load_module(tmp_path / "demo_module")

    assert [entry.xml_id for entry in parsed.acl_entries] == ["access_demo"]


def test_acl_group_without_module_prefix_is_qualified_by_declaring_module():
    graph = _build_graph("sale", [_entry("access_sale_user", "group_sale_salesman")])

    assert _group_targets(graph, "acl:sale.access_sale_user") == {"group:sale.group_sale_salesman"}


def test_acl_group_already_qualified_is_unchanged():
    graph = _build_graph("sale", [_entry("access_sale_base", "base.group_user")])

    assert _group_targets(graph, "acl:sale.access_sale_base") == {"group:base.group_user"}


def test_acl_without_group_has_no_group_edge():
    graph = _build_graph("sale", [_entry("access_sale_open", None)])

    assert _group_targets(graph, "acl:sale.access_sale_open") == set()
