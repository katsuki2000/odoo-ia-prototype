"""
code_intelligence/tests/test_bug5_declares_structured_extraction.py

todo/contexte.txt section 830: regression test for replacing
`re.findall(r"(\\S+) \\(declares\\)", observation)` in
predispatch_structure.py::dispatch_inheritance with a direct call to
list_involved_modules_with_evidence() -- Family 1 anti-pattern identified
by a parallel Claude Code session (re-parsing our own formatted tool text
with a regex, when the structured data it was built from is already
available via list_involved_modules_with_evidence()).

Two things are guarded here:
1. Functional equivalence -- the structured extraction returns the exact
   same declaring-module list the old regex extracted, on every model in
   the Bloc N1 perimeter (verified once already, interactively, against
   the real graph before this fix landed -- see section 830).
2. Structural guard -- the fragile regex pattern does not silently
   reappear in predispatch_structure.py.
"""

import re

from code_intelligence.graph.loader import get_code_intelligence_graph
from code_intelligence.agent.tool_helpers import set_graph_ref, _resolve_model_param
from code_intelligence.agent.tools.introspection import (
    list_involved_modules,
    list_involved_modules_with_evidence,
)

_BLOC_N1_MODELS = [
    "stock.picking", "stock.move", "account.move", "purchase.order",
    "sale.order", "maintenance.equipment",
]


def _old_regex_declaring_modules(observation: str):
    """Reproduces the exact behavior being replaced, for comparison only."""
    return re.findall(r"(\S+) \(declares\)", observation)


def _new_structured_declaring_modules(G, model_name: str):
    resolved = _resolve_model_param(model_name)
    return [
        mod for mod, role in list_involved_modules_with_evidence(G, resolved).modules
        if role == "declares"
    ]


def test_structured_extraction_matches_old_regex_on_bloc_n1_perimeter():
    G = get_code_intelligence_graph()
    set_graph_ref(G)
    for model_name in _BLOC_N1_MODELS:
        observation = str(list_involved_modules.func(model_name))
        old_way = _old_regex_declaring_modules(observation)
        new_way = _new_structured_declaring_modules(G, model_name)
        assert old_way == new_way, (
            f"structured extraction diverges from the old regex for {model_name!r}: "
            f"old={old_way!r} new={new_way!r}"
        )
        # Sanity: every model in this fixed perimeter has exactly one
        # declaring module, so an empty/multi result would itself be a
        # red flag worth investigating rather than a silent pass.
        assert len(new_way) == 1, f"expected exactly 1 declaring module for {model_name!r}, got {new_way!r}"


def test_declares_regex_pattern_not_reintroduced_in_predispatch_structure():
    """Structural guard: the Family 1 anti-pattern (re-parsing our own
    formatted 'X (declares)' text with a regex) must not silently
    reappear in this file. Checked on non-comment lines only -- the fix's
    own explanatory comment quotes the old pattern verbatim on purpose."""
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[2]
    source = (repo_root / "code_intelligence/agent/predispatch_structure.py").read_text(encoding="utf-8")
    live_lines = [
        line for line in source.splitlines() if not line.strip().startswith("#")
    ]
    live_source = "\n".join(live_lines)
    assert r"\(declares\)" not in live_source, (
        "the 'X (declares)' regex anti-pattern has reappeared in "
        "predispatch_structure.py -- use list_involved_modules_with_evidence() "
        "directly instead (see todo/contexte.txt section 830)"
    )
