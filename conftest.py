"""Network isolation shared by every test package.

Forces EMBEDDING_BACKEND=local_light (ChromaDB default ONNX all-MiniLM-L6-v2,
fully offline) whatever the project .env contains, so tests never reach a
local or remote embedding endpoint configured for real application use.

Tests that exercise resolve_embedding_function() with a specific backend pass
it as an argument and are not affected by this fixture.
"""

import pytest


@pytest.fixture(autouse=True)
def _force_offline_embedding_backend(monkeypatch):
    monkeypatch.setenv("EMBEDDING_BACKEND", "local_light")
    # Semantic retrieval is on by default in production; tests stay offline and
    # opt in explicitly (see test_semantic_retrieval.py).
    monkeypatch.setenv("RESOLVER_SEMANTIC_RETRIEVAL_ENABLED", "false")
