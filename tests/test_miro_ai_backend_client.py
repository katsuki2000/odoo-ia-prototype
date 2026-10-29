import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

MODULE_PATH = Path(__file__).resolve().parents[1] / "odoo_addons/miro_ai/controllers/backend_client.py"
API_URL = "http://backend:8000"


@pytest.fixture
def backend_client(monkeypatch):
    spec = importlib.util.spec_from_file_location("miro_backend_client", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _post(backend_client):
    return backend_client.post_to_backend(API_URL, "/api/v1/ask", {}, {"question": "q"}, 30)


def test_returns_response_from_configured_url(backend_client, monkeypatch):
    response = MagicMock(status_code=200)
    monkeypatch.setattr(backend_client.requests, "post", MagicMock(return_value=response))

    assert _post(backend_client) is response


def test_read_timeout_is_reported_without_retry(backend_client, monkeypatch):
    post = MagicMock(side_effect=requests.exceptions.ReadTimeout("slow"))
    monkeypatch.setattr(backend_client.requests, "post", post)

    with pytest.raises(backend_client.BackendTimeout):
        _post(backend_client)

    assert post.call_count == 1


def test_http_error_response_is_returned_without_retry(backend_client, monkeypatch):
    response = MagicMock(status_code=500)
    post = MagicMock(return_value=response)
    monkeypatch.setattr(backend_client.requests, "post", post)

    assert _post(backend_client) is response
    assert post.call_count == 1


@pytest.mark.parametrize(
    "error",
    [requests.exceptions.ConnectionError("refused"), requests.exceptions.ConnectTimeout("no route")],
)
def test_connection_error_does_not_retry_another_url(backend_client, monkeypatch, error):
    post = MagicMock(side_effect=error)
    monkeypatch.setattr(backend_client.requests, "post", post)

    with pytest.raises(backend_client.BackendError):
        _post(backend_client)
    assert post.call_count == 1


def _get(backend_client):
    return backend_client.get_from_backend(API_URL, "/api/v1/ask/jobs/abc", {}, 10)


def test_get_uses_configured_url_without_a_body(backend_client, monkeypatch):
    response = MagicMock(status_code=200)
    get = MagicMock(return_value=response)
    monkeypatch.setattr(backend_client.requests, "get", get)

    assert _get(backend_client) is response
    assert get.call_args.kwargs["json"] is None


def test_get_read_timeout_is_reported_without_retry(backend_client, monkeypatch):
    get = MagicMock(side_effect=requests.exceptions.ReadTimeout("slow"))
    monkeypatch.setattr(backend_client.requests, "get", get)

    with pytest.raises(backend_client.BackendTimeout):
        _get(backend_client)

    assert get.call_count == 1


def test_get_does_not_retry_another_url(backend_client, monkeypatch):
    get = MagicMock(side_effect=requests.exceptions.ConnectionError("refused"))
    monkeypatch.setattr(backend_client.requests, "get", get)

    with pytest.raises(backend_client.BackendUnreachable):
        _get(backend_client)
    assert get.call_count == 1


def test_backend_client_has_no_machine_specific_fallback_urls(backend_client):
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "localhost" not in source
    assert "127.0.0.1" not in source
    assert "miro_rag" not in source
