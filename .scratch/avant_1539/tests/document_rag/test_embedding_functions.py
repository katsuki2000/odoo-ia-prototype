"""Unit tests for embedding functions and provider resolution."""

from unittest.mock import patch, MagicMock
import pytest

from document_rag.vectorstore.embedding_functions import (
    LocalServerEmbeddingFunction,
    resolve_embedding_function,
)


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
    for backend in ("ollama", "openai_compatible", "vllm"):
        fn = resolve_embedding_function(backend=backend)
        assert isinstance(fn, LocalServerEmbeddingFunction)


def test_resolve_embedding_function_unknown_raises():
    """Verify unknown embedding backend raises ValueError."""
    for backend in ("local_light", "local", "tei", "invalid_backend"):
        with pytest.raises(ValueError, match="Unknown EMBEDDING_BACKEND"):
            resolve_embedding_function(backend=backend)


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
        model="bge-m3:latest",
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


def _ok_response(embeddings):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"data": [{"embedding": e, "index": i} for i, e in enumerate(embeddings)]}
    return resp


def _local_server_fn(**kwargs):
    return LocalServerEmbeddingFunction(base_url="http://localhost:8000/v1", model="bge-m3", **kwargs)


def test_local_server_retries_on_connection_error_then_succeeds():
    """Une coupure de connexion isolee est relancee, sans exception pour l'appelant."""
    import requests
    fn = _local_server_fn()
    with patch("document_rag.vectorstore.embedding_functions.time.sleep") as mock_sleep, \
         patch("requests.post") as mock_post:
        mock_post.side_effect = [
            requests.exceptions.ConnectionError("Remote end closed connection"),
            _ok_response([[0.1, 0.2]]),
        ]
        results = fn(["doc"])
    assert mock_post.call_count == 2
    assert mock_sleep.call_count == 1
    assert list(results[0]) == [0.1, 0.2]


def test_local_server_raises_after_max_retries():
    """Apres max_retries echecs, l'erreur d'origine est relevee (jamais masquee)."""
    import requests
    fn = _local_server_fn(max_retries=3)
    with patch("document_rag.vectorstore.embedding_functions.time.sleep"), \
         patch("requests.post") as mock_post:
        mock_post.side_effect = requests.exceptions.Timeout("read timed out")
        with pytest.raises(requests.exceptions.Timeout):
            fn(["doc"])
    assert mock_post.call_count == 3


def test_local_server_does_not_retry_http_errors():
    """Une erreur HTTP (ex. 404 modele absent) n'est pas relancee."""
    import requests
    fn = _local_server_fn()
    with patch("document_rag.vectorstore.embedding_functions.time.sleep") as mock_sleep, \
         patch("requests.post") as mock_post:
        resp = MagicMock()
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError("404 model not found")
        mock_post.return_value = resp
        with pytest.raises(requests.exceptions.HTTPError):
            fn(["doc"])
    assert mock_post.call_count == 1
    mock_sleep.assert_not_called()


def test_local_server_batches_and_preserves_order():
    """40 textes avec batch_size=16 donnent 3 appels (16, 16, 8), ordre conserve."""
    fn = _local_server_fn(batch_size=16)
    texts = [f"doc {i}" for i in range(40)]

    def fake_post(url, json=None, headers=None, timeout=None):
        return _ok_response([[float(t.split()[1])] for t in json["input"]])

    with patch("requests.post", side_effect=fake_post) as mock_post:
        results = fn(texts)
    assert mock_post.call_count == 3
    assert [len(c.kwargs["json"]["input"]) for c in mock_post.call_args_list] == [16, 16, 8]
    assert [r[0] for r in results] == [float(i) for i in range(40)]


def test_local_server_timeout_configurable_by_env(monkeypatch):
    monkeypatch.setenv("LOCAL_EMBEDDING_TIMEOUT", "120")
    assert _local_server_fn().timeout == 120.0
    monkeypatch.delenv("LOCAL_EMBEDDING_TIMEOUT")
    assert _local_server_fn().timeout == 30.0
    assert _local_server_fn(timeout=5).timeout == 5.0
