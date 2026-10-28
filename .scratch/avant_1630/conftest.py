"""Shared test setup.

Embeddings go through the Ollama server; tests marked
embedding_server are skipped when it cannot be reached. The Odoo runtime is never contacted
except by tests marked integration.
"""

import os

import pytest

UNREACHABLE_ODOO_URL = "http://127.0.0.1:9"
EMBEDDING_PROBE_TIMEOUT_SECONDS = 5

# Modules import the hop budget from config.settings at import time: pin it before any test module is collected.
from config import settings as _settings

_settings.CI_MAX_HOPS = 20


def _embedding_server_error():
    """Return the failure of one real embedding call, or None when the server answers."""
    from config import settings
    from document_rag.vectorstore.embedding_functions import OllamaEmbeddingFunction

    try:
        OllamaEmbeddingFunction(
            base_url=settings.EMBEDDING_BASE_URL,
            model=settings.EMBEDDING_MODEL,
            api_key=settings.EMBEDDING_API_KEY,
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
def _disable_semantic_retrieval(monkeypatch):
    if os.environ.get("USE_REMOTE_EMBEDDINGS", "").lower() == "true":
        return
    from config import settings
    monkeypatch.setattr(settings, "RESOLVER_SEMANTIC_RETRIEVAL_ENABLED", False)


@pytest.fixture(autouse=True)
def _isolate_semantic_index_cache(monkeypatch, tmp_path):
    from config import settings

    monkeypatch.setattr(settings, "SEMANTIC_INDEX_CACHE_DIR", str(tmp_path / "semantic_index"))


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
