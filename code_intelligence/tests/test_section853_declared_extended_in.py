"""
code_intelligence/tests/test_section853_declared_extended_in.py

todo/contexte.txt section 853: trace_full_inheritance() must label each
source file by its actual per-declaration role (filepath_roles,
graph/builder.py) -- "Declared in" only for the file(s) with role
'declares', "Extended in" for the rest -- instead of the pre-853 behaviour
of slapping "Declared in" on every file matching a _name/_inherit regex
and relying on a custom-first sort to put the right one in front by luck.

Covers the 3 fallback points pmm required before mandating the fix:
  1. Exactly one 'declares' file -> clean split, stable order (no
     custom-first re-sort), no 'Extended in' section when there is
     nothing to extend.
  2. Zero or several 'declares' files -> fallback to the pre-853
     undifferentiated single-list behaviour, with a warning logged.
  3. filepath_roles missing entirely (older/unrebuilt graph) -> same
     fallback path (0 declares found).
"""

import logging

import networkx as nx

from code_intelligence.rules.structure import trace_full_inheritance


def _node(G, model, filepaths, filepath_roles=None):
    """Build a minimal model node with one dummy EXTENDS edge so
    trace_full_inheritance() reaches the filepaths/labelling code instead
    of short-circuiting on the "no inheritance at all" EMPTY branch."""
    G.add_node(
        f"model:{model}",
        node_type="Model",
        filepaths=filepaths,
        filepath_roles=filepath_roles or {},
    )
    G.add_node("model:mail.thread", node_type="Model")
    G.add_edge(f"model:{model}", "model:mail.thread", edge_type="EXTENDS")


class TestCleanSingleDeclares:
    def test_declared_in_only_the_declaring_file(self, tmp_path):
        native = tmp_path / "native.py"
        native.write_text("class X(models.Model):\n    _name = 'x.model'\n")
        custom = tmp_path / "custom.py"
        custom.write_text("class X(models.Model):\n    _inherit = 'x.model'\n")

        G = nx.DiGraph()
        _node(
            G, "x.model", [str(native), str(custom)],
            {str(native): "declares", str(custom): "extends"},
        )
        res = trace_full_inheritance(G, "x.model")
        assert f"Declared in: [native.py" in res.summary_text
        assert f"Extended in: [custom.py" in res.summary_text
        # the declaring file must not also appear under "Extended in"
        declared_section, extended_section = res.summary_text.split("Extended in:")
        assert "custom.py" not in declared_section
        assert res.declaration_sites[0][0] == str(native)

    def test_no_extended_in_section_when_nothing_extends(self, tmp_path):
        native = tmp_path / "solo.py"
        native.write_text("class X(models.Model):\n    _name = 'x.solo'\n")
        G = nx.DiGraph()
        _node(G, "x.solo", [str(native)], {str(native): "declares"})
        res = trace_full_inheritance(G, "x.solo")
        assert "Declared in:" in res.summary_text
        assert "Extended in:" not in res.summary_text

    def test_order_is_stable_not_custom_first(self, tmp_path):
        """Regression: pre-853 sorted ALL files custom-first. The fix must
        NOT re-sort 'Extended in' -- order follows filepaths as given."""
        native = tmp_path / "native.py"
        native.write_text("_name = 'x.model'\n")
        odoo_addons_dir = tmp_path / "odoo_addons" / "custom_mod"
        odoo_addons_dir.mkdir(parents=True)
        custom_first_in_list = tmp_path / "b_extends.py"
        custom_first_in_list.write_text("_inherit = 'x.model'\n")
        custom_last_in_list = odoo_addons_dir / "a_extends.py"
        custom_last_in_list.write_text("_inherit = 'x.model'\n")

        filepaths = [str(native), str(custom_first_in_list), str(custom_last_in_list)]
        roles = {
            str(native): "declares",
            str(custom_first_in_list): "extends",
            str(custom_last_in_list): "extends",
        }
        G = nx.DiGraph()
        _node(G, "x.model", filepaths, roles)
        res = trace_full_inheritance(G, "x.model")
        ext_section = res.summary_text.split("Extended in:")[1]
        # b_extends.py (given first among the extends files) must appear
        # before a_extends.py (given second) -- alphabetical/custom-first
        # sorting would have reversed this.
        assert ext_section.index("b_extends.py") < ext_section.index("a_extends.py")


class TestFallback:
    def test_zero_declares_falls_back_with_warning(self, tmp_path, caplog):
        fp1 = tmp_path / "one.py"
        fp1.write_text("_inherit = 'x.model'\n")
        fp2 = tmp_path / "two.py"
        fp2.write_text("_inherit = 'x.model'\n")
        G = nx.DiGraph()
        _node(G, "x.model", [str(fp1), str(fp2)], {})  # no roles at all
        with caplog.at_level(logging.WARNING):
            res = trace_full_inheritance(G, "x.model")
        assert "Extended in:" not in res.summary_text
        assert "Declared in:" in res.summary_text
        assert "one.py" in res.summary_text and "two.py" in res.summary_text
        assert any("falling back" in r.message for r in caplog.records)

    def test_multiple_declares_falls_back_with_warning(self, tmp_path, caplog):
        fp1 = tmp_path / "one.py"
        fp1.write_text("_name = 'x.model'\n")
        fp2 = tmp_path / "two.py"
        fp2.write_text("_name = 'x.model'\n")
        G = nx.DiGraph()
        _node(
            G, "x.model", [str(fp1), str(fp2)],
            {str(fp1): "declares", str(fp2): "declares"},
        )
        with caplog.at_level(logging.WARNING):
            res = trace_full_inheritance(G, "x.model")
        assert "Extended in:" not in res.summary_text
        assert "one.py" in res.summary_text and "two.py" in res.summary_text
        assert any("falling back" in r.message for r in caplog.records)
