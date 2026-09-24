"""
todo/contexte.txt section 925: dispatch_inheritance must inspect the declaring
module of the resolved model whenever the question names no module, even if a
third-party module also extends that model.

The graph is synthetic so the test depends on neither the indexed corpus nor
the machine's .env.
"""

from types import SimpleNamespace

import networkx as nx
import pytest

from code_intelligence.agent import tool_helpers
from code_intelligence.agent.context import DispatchContext
from code_intelligence.agent.predispatch_structure import dispatch_inheritance

_QUESTION = (
    "shop.order est-il un nouveau modele ou une extension ? Quel modele natif "
    "hors du perimetre 'vente' ce module etend-il directement ?"
)
_MODEL = "shop.order"
_DECLARING_MODULE = "shop"
_THIRD_PARTY_MODULE = "shop_order_type"


class RecordingTool:
    def __init__(self):
        self.calls = []

    def invoke(self, args):
        self.calls.append(args["model_name"])
        return f"observation for {args['model_name']}"


class FakeTraceLogger:
    def log_hop(self, *args, **kwargs):
        pass


def _build_graph(with_third_party: bool) -> nx.DiGraph:
    G = nx.DiGraph()
    G.add_node(f"model:{_MODEL}", node_type="Model", name=_MODEL, filepaths=[])
    G.add_node(f"module:{_DECLARING_MODULE}", node_type="Module", filepath="/srv/core/shop/__manifest__.py")
    G.add_edge(f"model:{_MODEL}", f"module:{_DECLARING_MODULE}", edge_type="DEFINED_IN", role="declares")
    if with_third_party:
        G.add_node(
            f"module:{_THIRD_PARTY_MODULE}", node_type="Module",
            filepath="/srv/third_party/shop_order_type/__manifest__.py",
        )
        G.add_edge(f"model:{_MODEL}", f"module:{_THIRD_PARTY_MODULE}", edge_type="DEFINED_IN", role="extends")
    return G


def _run_dispatch(monkeypatch, G, resolved_modules):
    monkeypatch.setattr(
        tool_helpers, "_is_custom_module_filepath", lambda fp: "third_party" in fp,
    )
    tool_helpers.set_graph_ref(G)
    mod_tool = RecordingTool()
    ctx = DispatchContext(
        G=G,
        concept=SimpleNamespace(
            is_resolved=True, resolved_models=[_MODEL], resolved_modules=resolved_modules,
        ),
        question=_QUESTION,
        tool_map={"list_involved_modules": mod_tool},
        resolved_user_group_xmlids=[],
        trace_logger=FakeTraceLogger(),
        trace_id="test",
        hop_cap=20,
    )
    dispatch_inheritance(ctx)
    return mod_tool.calls


def test_declaring_module_inspected_alongside_third_party_extension(monkeypatch):
    calls = _run_dispatch(monkeypatch, _build_graph(with_third_party=True), resolved_modules=[])
    assert _DECLARING_MODULE in calls
    assert _THIRD_PARTY_MODULE in calls


def test_declaring_module_inspected_without_third_party_extension(monkeypatch):
    calls = _run_dispatch(monkeypatch, _build_graph(with_third_party=False), resolved_modules=[])
    assert _DECLARING_MODULE in calls


def test_named_module_is_the_only_module_inspected(monkeypatch):
    calls = _run_dispatch(
        monkeypatch, _build_graph(with_third_party=True), resolved_modules=[_THIRD_PARTY_MODULE],
    )
    assert calls == [_THIRD_PARTY_MODULE]


@pytest.mark.parametrize("with_third_party", [True, False])
def test_model_mode_call_runs_when_no_module_is_named(monkeypatch, with_third_party):
    calls = _run_dispatch(monkeypatch, _build_graph(with_third_party), resolved_modules=[])
    assert _MODEL in calls
