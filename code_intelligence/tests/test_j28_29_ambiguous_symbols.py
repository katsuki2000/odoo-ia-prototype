"""
code_intelligence/tests/test_j28_29_ambiguous_symbols.py

 : a model declared with _name in one module and extended
via _inherit in one or more OTHER modules is a genuinely ambiguous
symbol -- there is no single "real" origin module. Before this story,
graph_builder.py created a single DEFINED_IN edge from decls[0]'s
filepath, arbitrarily hiding every other module. This locks the fix:
  - cross_file_resolver.build_module_symbol_registry populating
    registry.model_modules in lockstep with registry.models.
  - graph_builder creating one DEFINED_IN edge PER declaration (not just
    decls[0]'s module), tagged with role="declares"/"extends".
  - auxiliary_tools.list_involved_modules_with_role() surfacing every
    candidate with its role instead of collapsing to one.
  - the list_involved_modules @tool wrapper presenting all candidates
    with an explicit ambiguity note instead of silently picking one.
"""
import networkx as nx
import pytest

from code_intelligence.cross_file_resolver import (
    ParsedModule,
    build_module_symbol_registry,
)
from code_intelligence.python_extractor import OdooModelDeclaration
from code_intelligence.graph_builder import OdooGraphBuilder
from code_intelligence.auxiliary_tools import (
    list_involved_modules,
    list_involved_modules_with_role,
)


def _make_modules_dict():
    """
    Synthetic corpus: 'base_mod' declares custom.foo (_name), and TWO
    other independent modules ('ext_a', 'ext_b') each extend it via
    _inherit only -- the real-world shape this  (a model
    touched by several unrelated customization modules).
    """
    base_decl = OdooModelDeclaration(
        class_name="CustomFoo",
        filepath="/corpus/base_mod/models/custom_foo.py",
        lineno=1,
        name="custom.foo",
    )
    ext_a_decl = OdooModelDeclaration(
        class_name="CustomFooExtA",
        filepath="/corpus/ext_a/models/custom_foo.py",
        lineno=1,
        inherit=["custom.foo"],
    )
    ext_b_decl = OdooModelDeclaration(
        class_name="CustomFooExtB",
        filepath="/corpus/ext_b/models/custom_foo.py",
        lineno=1,
        inherit=["custom.foo"],
    )

    return {
        "base_mod": ParsedModule(manifest=None, models=[base_decl]),
        "ext_a": ParsedModule(manifest=None, models=[ext_a_decl]),
        "ext_b": ParsedModule(manifest=None, models=[ext_b_decl]),
    }


def test_registry_tracks_module_per_declaration_not_just_first():
    """cross_file_resolver: model_modules must list every module that
    declared/extended the model, in the same count as models[]."""
    registry = build_module_symbol_registry(_make_modules_dict())

    assert len(registry.models["custom.foo"]) == 3
    assert set(registry.model_modules["custom.foo"]) == {"base_mod", "ext_a", "ext_b"}
    assert len(registry.model_modules["custom.foo"]) == 3


def test_graph_builder_creates_one_defined_in_edge_per_module():
    """graph_builder: must NOT collapse to decls[0]'s module -- every
    module touching the model gets its own DEFINED_IN edge, tagged with
    its role (declares vs extends)."""
    modules_dict = _make_modules_dict()
    registry = build_module_symbol_registry(modules_dict)
    builder = OdooGraphBuilder(registry, modules_dict)
    G = builder.build_graph()

    model_node = "model:custom.foo"
    defined_in_targets = {
        (v.replace("module:", ""), data.get("role"))
        for _u, v, data in G.out_edges(model_node, data=True)
        if data.get("edge_type") == "DEFINED_IN"
    }

    assert defined_in_targets == {
        ("base_mod", "declares"),
        ("ext_a", "extends"),
        ("ext_b", "extends"),
    }


def test_lister_modules_impliques_avec_role_returns_all_candidates():
    """auxiliary_tools: the ambiguous-symbol-aware variant must return
    every candidate module with its correct role, never just one."""
    modules_dict = _make_modules_dict()
    registry = build_module_symbol_registry(modules_dict)
    builder = OdooGraphBuilder(registry, modules_dict)
    G = builder.build_graph()

    entries = list_involved_modules_with_role(G, "custom.foo")
    assert sorted(entries) == sorted([
        ("base_mod", "declares"),
        ("ext_a", "extends"),
        ("ext_b", "extends"),
    ])


def test_lister_modules_impliques_still_returns_flat_list_backward_compat():
    """Backward compatibility: the original flat-list function keeps its
    signature/behavior for existing callers (e.g. test_b2_auxiliary_tools),
    but can now legitimately return several modules for one model."""
    modules_dict = _make_modules_dict()
    registry = build_module_symbol_registry(modules_dict)
    builder = OdooGraphBuilder(registry, modules_dict)
    G = builder.build_graph()

    modules = list_involved_modules(G, "custom.foo")
    assert sorted(modules) == ["base_mod", "ext_a", "ext_b"]


def test_single_module_model_has_no_false_ambiguity():
    """Sanity check: a model declared in only one module still resolves
    to exactly one candidate -- no false ambiguity introduced by the fix."""
    solo_decl = OdooModelDeclaration(
        class_name="SoloModel",
        filepath="/corpus/solo_mod/models/solo.py",
        lineno=1,
        name="solo.model",
    )
    modules_dict = {"solo_mod": ParsedModule(manifest=None, models=[solo_decl])}
    registry = build_module_symbol_registry(modules_dict)
    builder = OdooGraphBuilder(registry, modules_dict)
    G = builder.build_graph()

    entries = list_involved_modules_with_role(G, "solo.model")
    assert entries == [("solo_mod", "declares")]


def test_ci_agent_tool_wrapper_flags_ambiguity_with_roles():
    """ci_agent_tools @tool wrapper: must present all candidates with
    role and an explicit ambiguity note, never silently pick one."""
    from code_intelligence import ci_agent_tools

    G = nx.DiGraph()
    G.add_node("model:custom.foo", node_type="Model", name="custom.foo")
    G.add_edge("model:custom.foo", "module:base_mod", edge_type="DEFINED_IN", role="declares")
    G.add_edge("model:custom.foo", "module:ext_a", edge_type="DEFINED_IN", role="extends")

    ci_agent_tools.set_graph_ref(G)
    result = ci_agent_tools.list_involved_modules.invoke({"model_name": "custom.foo"})

    assert "base_mod (declares)" in result
    assert "ext_a (extends)" in result
    assert "SYMBOLE AMBIGU" in result


def test_ci_agent_tool_wrapper_no_ambiguity_note_for_single_candidate():
    """A model with exactly one candidate module must NOT carry the
    ambiguity note -- it would be noise for the common, unambiguous case."""
    from code_intelligence import ci_agent_tools

    G = nx.DiGraph()
    G.add_node("model:solo.model", node_type="Model", name="solo.model")
    G.add_edge("model:solo.model", "module:solo_mod", edge_type="DEFINED_IN", role="declares")

    ci_agent_tools.set_graph_ref(G)
    result = ci_agent_tools.list_involved_modules.invoke({"model_name": "solo.model"})

    assert "solo_mod (declares)" in result
    assert "SYMBOLE AMBIGU" not in result
