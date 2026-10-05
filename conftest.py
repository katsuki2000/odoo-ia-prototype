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

import pytest


@pytest.fixture(autouse=True)
def _force_offline_embedding_backend(monkeypatch):
    monkeypatch.setenv("EMBEDDING_BACKEND", "local_light")
    # Semantic retrieval is on by default in production; tests stay offline and
    # opt in explicitly (see test_semantic_retrieval.py).
    monkeypatch.setenv("RESOLVER_SEMANTIC_RETRIEVAL_ENABLED", "false")


@pytest.fixture(autouse=True)
def _isolate_odoo_runtime(request, monkeypatch):
    if request.node.get_closest_marker("integration") is None:
        monkeypatch.setenv("ODOO_URL", UNREACHABLE_ODOO_URL)
