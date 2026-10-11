"""Network isolation shared by every test package.

Forces EMBEDDING_BACKEND=local_light (ChromaDB default ONNX all-MiniLM-L6-v2,
fully offline) whatever the project .env contains, so tests never reach a
local or remote embedding endpoint configured for real application use.

Tests that exercise resolve_embedding_function() with a specific backend pass
it as an argument and are not affected by this fixture.

ODOO_URL is pointed at a closed port so a running Odoo server never changes
what the code intelligence graph loads; tests marked integration keep the
configured URL.
"""

UNREACHABLE_ODOO_URL = "http://127.0.0.1:9"

import os

import pytest

# Read at import time by config.settings: pinned before any test module is collected so the
# hop budget the tests assert does not depend on the developer .env.
os.environ["CI_MAX_HOPS"] = "20"


@pytest.fixture(autouse=True)
def _force_offline_embedding_backend(monkeypatch):
    monkeypatch.setenv("EMBEDDING_BACKEND", "local_light")
    # Semantic retrieval is on by default in production; tests stay offline and
    # opt in explicitly (see test_semantic_retrieval.py).
    monkeypatch.setenv("RESOLVER_SEMANTIC_RETRIEVAL_ENABLED", "false")


@pytest.fixture(autouse=True)
def _isolate_semantic_index_cache(monkeypatch, tmp_path):
    from config import settings

    monkeypatch.setattr(settings, "SEMANTIC_INDEX_CACHE_DIR", str(tmp_path / "semantic_index"))


@pytest.fixture(autouse=True)
def _isolate_tool_helpers_graph_ref():
    """Undo any set_graph_ref() made by a test body so the next test in the same worker
    never inherits it. Module-scoped fixtures run before this one, so a graph they set is
    part of the saved value and stays in place for the whole module."""
    import sys

    module_name = "code_intelligence.agent.tool_helpers"
    loaded = sys.modules.get(module_name)
    previous = loaded.get_graph_ref() if loaded is not None else None
    yield
    loaded = sys.modules.get(module_name)
    if loaded is not None:
        loaded.set_graph_ref(previous)


@pytest.fixture(scope="module")
def offline_odoo_runtime():
    """Module-scoped fixtures run before function-scoped autouse ones, so a graph built
    in one needs this explicit request to stay independent of a running Odoo."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("ODOO_URL", UNREACHABLE_ODOO_URL)
        yield


@pytest.fixture(autouse=True)
def _isolate_odoo_runtime(request, monkeypatch):
    if request.node.get_closest_marker("integration") is None:
        monkeypatch.setenv("ODOO_URL", UNREACHABLE_ODOO_URL)
