"""Unit tests for embedding functions and provider resolution."""

import os
from unittest.mock import patch, MagicMock
import pytest

from document_rag.vectorstore.embedding_functions import (
    CustomNomicEmbeddingFunction,
    LocalServerEmbeddingFunction,
    resolve_embedding_function,
)


def test_resolve_embedding_function_local_light_returns_none():
    """Verify that local_light returns None to trigger Chroma's ONNX all-MiniLM-L6-v2."""
    fn = resolve_embedding_function(backend="local_light")
    assert fn is None


def test_resolve_embedding_function_local_server_returns_instance():
    """Verify that local_server returns LocalServerEmbeddingFunction."""
    with patch("config.settings.LOCAL_EMBEDDING_BASE_URL", "http://localhost:11434/v1"), \
         patch("config.settings.LOCAL_EMBEDDING_MODEL", "all-minilm:latest"), \
         patch("config.settings.LOCAL_EMBEDDING_API_KEY", "ollama"):
        fn = resolve_embedding_function(backend="local_server")
        assert isinstance(fn, LocalServerEmbeddingFunction)
        assert fn.model == "all-minilm:latest"
        assert fn.endpoint == "http://localhost:11434/v1/embeddings"


def test_resolve_embedding_function_ollama_and_openai_synonyms():
    """Verify synonyms 'ollama' and 'openai_compatible' return LocalServerEmbeddingFunction."""
    for backend in ("ollama", "openai_compatible", "vllm", "tei"):
        fn = resolve_embedding_function(backend=backend)
        assert isinstance(fn, LocalServerEmbeddingFunction)


def test_resolve_embedding_function_unknown_raises():
    """Verify unknown embedding backend raises ValueError."""
    with pytest.raises(ValueError, match="Unknown EMBEDDING_BACKEND"):
        resolve_embedding_function(backend="invalid_backend")


def test_local_server_embedding_function_openai_format():
    """Verify LocalServerEmbeddingFunction correctly parses OpenAI standard response."""
    fn = LocalServerEmbeddingFunction(
        base_url="http://localhost:8000/v1",
        model="bge-small-en-v1.5",
        api_key="test-key",
    )
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"embedding": [0.1, 0.2, 0.3], "index": 0},
                {"embedding": [0.4, 0.5, 0.6], "index": 1},
            ]
        }
        mock_post.return_value = mock_resp

        results = fn(["first doc", "second doc"])
        assert len(results) == 2
        assert list(results[0]) == [0.1, 0.2, 0.3]
        assert list(results[1]) == [0.4, 0.5, 0.6]


def test_local_server_embedding_function_ollama_native_format():
    """Verify LocalServerEmbeddingFunction correctly parses Ollama native response."""
    fn = LocalServerEmbeddingFunction(
        base_url="http://localhost:11434",
        model="nomic-embed-text",
        api_key="ollama",
    )
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "embeddings": [[0.7, 0.8, 0.9]]
        }
        mock_post.return_value = mock_resp

        results = fn(["single document"])
        assert len(results) == 1
        assert list(results[0]) == [0.7, 0.8, 0.9]


def test_custom_nomic_embedding_function_calls_endpoint():
    """Verify CustomNomicEmbeddingFunction calls Nomic REST endpoint."""
    fn = CustomNomicEmbeddingFunction(
        model="nomic-embed-text-v1.5",
        api_key="test-nomic-key",
    )
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"embeddings": [[0.05, 0.06]]}
        mock_post.return_value = mock_resp

        results = fn(["sample text"])
        assert list(results[0]) == [0.05, 0.06]


def test_resolve_embedding_function_local_custom_model():
    """Verify backend='local' dynamically instantiates LocalSentenceTransformerEmbeddingFunction with custom model."""
    with patch("document_rag.vectorstore.embedding_functions.LocalSentenceTransformerEmbeddingFunction") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance

        fn = resolve_embedding_function(backend="local", embedding_model="BAAI/bge-m3")
        assert fn == mock_instance
        mock_cls.assert_called_once_with(model_name="BAAI/bge-m3")

