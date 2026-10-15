"""
code_intelligence/tests/test_bloc8_j27_inheritance_cycle_regression.py

 / J27: "Cycles d'héritage — test de non-régression avec cycle
artificiel injecté dans le corpus de test (détection déjà posée en A2, à
couvrir en non-régression ici)."

test_a2_1_1.py::test_inheritance_cycle_detection already unit-tests cycle
DETECTION in isolation (build_module_symbol_registry() on a 2-model cycle,
asserting registry.detected_cycles is non-empty). That is necessary but not
sufficient for this plan item: it never proves the rest of the pipeline
(OdooGraphBuilder.build_graph(), then a real graph QUERY that walks EXTENDS
edges) survives the same cycle without hanging or crashing. graph_builder.py
itself only ADDS edges (no traversal at build time, so it can't hang), but
deterministic_tools.trace_full_inheritance() does a BFS over EXTENDS/
DELEGATES_TO edges to answer "trace the full inheritance chain" -- exactly
the kind of consumer that WOULD infinite-loop on a cycle if its visited-set
guard were ever removed or broken by a future edit.

These tests build the cycle through the full corpus-load path (ParsedModule
-> build_module_symbol_registry -> OdooGraphBuilder.build_graph(), the same
sequence rag/graph.py's _load_module()/get_code_intelligence_graph() uses
for real modules), then query the resulting graph with the actual
trace_full_inheritance() tool implementation -- proving the whole chain,
not just the detection step, is cycle-safe. A wall-clock assertion gives
the "chiffre documenté" the  critère de fin asks for: any regression
that reintroduces unbounded recursion on a cycle would blow well past this
budget, never just run slightly slower.
"""

import time

import networkx as nx

from code_intelligence.extractor.manifest import OdooManifest
from code_intelligence.extractor.python import OdooModelDeclaration
from code_intelligence.graph.nodes import ParsedModule
from code_intelligence.graph.symbols import build_module_symbol_registry
from code_intelligence.graph.builder import OdooGraphBuilder
from code_intelligence.rules.structure import trace_full_inheritance
from code_intelligence.rules.common import QueryStatus

# Generous budget for a query over a handful of synthetic nodes -- the point
# is to catch UNBOUNDED recursion (which would hang indefinitely or blow
# the recursion limit), not to benchmark real latency (that's ).
_MAX_QUERY_SECONDS = 2.0


def _build_graph_from_models(models_by_module: dict):
    """Run the real corpus-load sequence (registry -> graph) on hand-built
    ParsedModules, mirroring rag/graph.py's _load_module() path."""
    modules_dict = {
        mod_name: ParsedModule(
            manifest=OdooManifest(module_name=mod_name, filepath="", depends=[]),
            models=decls,
        )
        for mod_name, decls in models_by_module.items()
    }
    registry = build_module_symbol_registry(modules_dict)
    G = OdooGraphBuilder(registry, modules_dict).build_graph()
    return G, registry


def test_two_model_cycle_survives_full_graph_build_and_query():
    """
    2-model cycle (model.a <-> model.b), same shape as
    test_a2_1_1.py::test_inheritance_cycle_detection, but pushed all the
    way through graph construction AND a real trace_full_inheritance()
    query instead of stopping at registry.detected_cycles.
    """
    models = [
        OdooModelDeclaration(
            class_name="ModelA", filepath="cycle_mod/a.py", lineno=1,
            name="model.a", inherit=["model.b"],
        ),
        OdooModelDeclaration(
            class_name="ModelB", filepath="cycle_mod/b.py", lineno=1,
            name="model.b", inherit=["model.a"],
        ),
    ]
    G, registry = _build_graph_from_models({"cycle_mod": models})

    # Detection (A2) still holds through the full corpus-load path, not
    # only when build_module_symbol_registry() is called in isolation.
    assert len(registry.detected_cycles) > 0

    # Graph construction itself must have completed (no exception, no hang)
    # -- reaching this line already proves build_graph() didn't loop.
    assert G.has_node("model:model.a")
    assert G.has_node("model:model.b")
    assert G.has_edge("model:model.a", "model:model.b")
    assert G.has_edge("model:model.b", "model:model.a")

    t0 = time.perf_counter()
    result = trace_full_inheritance(G, "model.a")
    elapsed = time.perf_counter() - t0

    assert elapsed < _MAX_QUERY_SECONDS, (
        f"trace_full_inheritance took {elapsed:.3f}s on a 2-model cycle -- "
        f"expected well under {_MAX_QUERY_SECONDS}s; a regression in the "
        "visited-set guard would show up here as a hang, not a slowdown."
    )
    assert result.status == QueryStatus.FOUND
    # BFS must terminate having visited each model exactly once -- a broken
    # visited-guard would either loop forever (caught above by the time
    # budget) or silently duplicate model.b in full_ancestors.
    assert result.full_ancestors == ["model.b"]
    assert result.extension_parents == ["model.b"]


def test_three_model_cascade_cycle_survives_full_graph_build_and_query():
    """Same as above but a 3-model cascade cycle (a -> b -> c -> a), closer
    to a realistic multi-level extension chain that happens to loop back."""
    models = [
        OdooModelDeclaration(
            class_name="ModelA", filepath="cycle_mod3/a.py", lineno=1,
            name="cascade.a", inherit=["cascade.b"],
        ),
        OdooModelDeclaration(
            class_name="ModelB", filepath="cycle_mod3/b.py", lineno=1,
            name="cascade.b", inherit=["cascade.c"],
        ),
        OdooModelDeclaration(
            class_name="ModelC", filepath="cycle_mod3/c.py", lineno=1,
            name="cascade.c", inherit=["cascade.a"],
        ),
    ]
    G, registry = _build_graph_from_models({"cycle_mod3": models})

    assert len(registry.detected_cycles) > 0
    for m in ("cascade.a", "cascade.b", "cascade.c"):
        assert G.has_node(f"model:{m}")

    t0 = time.perf_counter()
    result = trace_full_inheritance(G, "cascade.a")
    elapsed = time.perf_counter() - t0

    assert elapsed < _MAX_QUERY_SECONDS, (
        f"trace_full_inheritance took {elapsed:.3f}s on a 3-model cascade "
        f"cycle -- expected well under {_MAX_QUERY_SECONDS}s."
    )
    assert result.status == QueryStatus.FOUND
    assert set(result.full_ancestors) == {"cascade.b", "cascade.c"}
    assert len(result.full_ancestors) == 2  # no duplicate visits


def test_self_inheriting_model_survives_full_graph_build_and_query():
    """
    Degenerate edge case: a model whose own _inherit lists itself (the Odoo
    in-place extension pattern, or a copy-paste typo). The builder skips the
    EXTENDS edge from a model to itself (section 1347: it has no meaning), so
    the graph has no self-loop and the query must still terminate.
    """
    models = [
        OdooModelDeclaration(
            class_name="SelfModel", filepath="self_mod/a.py", lineno=1,
            name="self.model", inherit=["self.model"],
        ),
    ]
    G, registry = _build_graph_from_models({"self_mod": models})

    assert G.has_node("model:self.model")
    assert not G.has_edge("model:self.model", "model:self.model")

    t0 = time.perf_counter()
    result = trace_full_inheritance(G, "self.model")
    elapsed = time.perf_counter() - t0

    assert elapsed < _MAX_QUERY_SECONDS, (
        f"trace_full_inheritance took {elapsed:.3f}s on a self-inheriting "
        f"model -- expected well under {_MAX_QUERY_SECONDS}s."
    )
    # No EXTENDS edge was built, so the model has no parent to report.
    assert result.status == QueryStatus.EMPTY
    assert result.full_ancestors == []
    assert result.extension_parents == []


def test_trace_full_inheritance_stops_on_a_self_loop_already_in_the_graph():
    """
    The builder no longer creates a self-loop, but a graph loaded from an older
    cache may still contain one: the visited-set guard must stop the BFS from
    re-enqueuing the model a second time.
    """
    G = nx.DiGraph()
    G.add_node("model:self.model", node_type="Model", name="self.model")
    G.add_edge("model:self.model", "model:self.model", edge_type="EXTENDS")

    result = trace_full_inheritance(G, "self.model")

    assert result.status == QueryStatus.FOUND
    assert result.full_ancestors == []
    assert result.extension_parents == ["self.model"]
