"""Section 1627: align importers with the removal of core/routing/routing_keywords.py."""
import re


def edit(path, pairs):
    s = open(path, encoding="utf-8").read()
    for old, new in pairs:
        assert s.count(old) == 1, (path, old[:60], s.count(old))
        s = s.replace(old, new)
    open(path, "w", encoding="utf-8").write(s)


# (1) core/routing/__init__.py : full rewrite (only routing.py remains)
open("core/routing/__init__.py", "w", encoding="utf-8").write('''"""
core/routing/__init__.py

Regroupement : routing.py (choix de la source : documentation ou systeme).
"""

from .routing import (
    logger,
    route,
    route_decision,
)

__all__ = [
    "logger",
    "route",
    "route_decision",
]
''')

# graph_compat.py : keep only the names routing.py still provides
p = "core/graph/graph_compat.py"
s = open(p, encoding="utf-8").read()
start = s.index("from core.routing.routing import (")
end = s.index(")\n", start) + 2
s = s[:start] + "from core.routing.routing import (\n    route,\n    route_decision,\n)\n" + s[end:]
open(p, "w", encoding="utf-8").write(s)

# (2) graph_nodes.py
edit("core/graph/graph_nodes.py", [
    ("from core.routing.routing_keywords import _fold_accents, has_explicit_doc_request\n", ""),
    ("""def _has_explicit_doc_request(state: RAGState) -> bool:
    return has_explicit_doc_request(_fold_accents(state.get('question', '').lower()))


""", ""),
    ("""    if state.get('ci_evidence_sufficiency') and _has_explicit_doc_request(state):
        return 'generate'
""", ""),
])

# (3) run_rag_model_eval.py : same folding, inline
edit("scripts/run_rag_model_eval.py", [
    ("from core.routing.routing_keywords import _fold_accents\n", ""),
    ("import time\nfrom pathlib import Path\n", "import time\nimport unicodedata\nfrom pathlib import Path\n"),
    ("def normalize(text):", '''def _fold_accents(text):
    """Strip diacritics (NFD, combining marks removed)."""
    return "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")


def normalize(text):'''),
])

# (4) tests/test_route_accent_fold.py
t = "tests/test_route_accent_fold.py"
s = open(t, encoding="utf-8").read()
head_end = s.index("def _route_question")
s = '''# -*- coding: utf-8 -*-
import pytest
from unittest.mock import patch
from core.graph.graph import route
from core.routing.source_selection import SourceSelection


''' + s[head_end:]
a = s.index("# ── _fold_accents unit behavior")
b = s.index("# ── Routing consumes the selector signal")
s = s[:a] + s[b:]
for banned in ("_fold_accents", "has_explicit_doc_request", "_KEYWORDS", "DOC_ANCHORS", "THRESHOLD_QUERY_TERMS"):
    assert banned not in s, banned
open(t, "w", encoding="utf-8").write(s)
print("ok")
