"""Shared test setup.

Embeddings go through the inference server (EMBEDDING_BACKEND=local_server); tests marked
embedding_server are skipped when it cannot be reached. The Odoo runtime is never contacted
except by tests marked integration.
"""

import os

import pytest

UNREACHABLE_ODOO_URL = "http://127.0.0.1:9"
EMBEDDING_PROBE_TIMEOUT_SECONDS = 5

# Read at import time by config.settings: pinned before any test module is collected so the
# hop budget the tests assert does not depend on the developer .env.
os.environ["CI_MAX_HOPS"] = "20"


def _embedding_server_error():
    """Return the failure of one real embedding call, or None when the server answers."""
    from config import settings
    from document_rag.vectorstore.embedding_functions import LocalServerEmbeddingFunction

    try:
        LocalServerEmbeddingFunction(
            base_url=settings.LOCAL_EMBEDDING_BASE_URL,
            model=settings.LOCAL_EMBEDDING_MODEL,
            api_key=settings.LOCAL_EMBEDDING_API_KEY,
            timeout=EMBEDDING_PROBE_TIMEOUT_SECONDS,
            max_retries=1,
        )(["ping"])
    except Exception as error:
        return error
    return None


def pytest_collection_modifyitems(items):
    needing = [item for item in items if item.get_closest_marker("embedding_server")]
    if not needing:
        return
    error = _embedding_server_error()
    if error is None:
        return
    skip = pytest.mark.skip(reason=f"embedding server unavailable ({type(error).__name__})")
    for item in needing:
        item.add_marker(skip)


@pytest.fixture(autouse=True)
def _pin_embedding_backend(monkeypatch):
    if os.environ.get("USE_KAGGLE_EMBEDDINGS", "").lower() == "true":
        return
    monkeypatch.setenv("EMBEDDING_BACKEND", "local_server")
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

    module_name = "code_intelligence.agent.tools.helpers"
    loaded = sys.modules.get(module_name)
    previous = loaded.get_graph_ref() if loaded is not None else None
    yield
    loaded = sys.modules.get(module_name)
    if loaded is not None:
        loaded.set_graph_ref(previous)


@pytest.fixture(scope="module")
def real_graph():
    """Real graph registered as the active graph for one test module, then restored."""
    from code_intelligence.agent.tools import helpers
    from code_intelligence.graph.loader import get_code_intelligence_graph

    previous = helpers.get_graph_ref()
    graph = get_code_intelligence_graph()
    helpers.set_graph_ref(graph)
    yield graph
    helpers.set_graph_ref(previous)


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
