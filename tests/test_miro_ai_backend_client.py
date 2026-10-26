import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

MODULE_PATH = Path(__file__).resolve().parents[1] / "odoo_addons/miro_ai/controllers/backend_client.py"
CANDIDATES = ["http://127.0.0.1:8000", "http://localhost:8000"]


@pytest.fixture
def backend_client(monkeypatch):
    settings_stub = types.ModuleType("odoo.addons.miro_ai.models.miro_ai_settings")
    settings_stub.DEFAULT_API_URL = "http://127.0.0.1:8000"
    for name in ("odoo", "odoo.addons", "odoo.addons.miro_ai", "odoo.addons.miro_ai.models"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, settings_stub.__name__, settings_stub)
    spec = importlib.util.spec_from_file_location("miro_backend_client", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _post(backend_client):
    return backend_client.post_with_failover(CANDIDATES, "/api/v1/ask", {}, {"question": "q"}, 30)


def test_returns_the_first_response_and_its_url(backend_client, monkeypatch):
    response = MagicMock(status_code=200)
    monkeypatch.setattr(backend_client.requests, "post", MagicMock(return_value=response))

    assert _post(backend_client) == (response, CANDIDATES[0])


def test_read_timeout_is_not_sent_again_to_the_next_candidate(backend_client, monkeypatch):
    post = MagicMock(side_effect=requests.exceptions.ReadTimeout("slow"))
    monkeypatch.setattr(backend_client.requests, "post", post)

    with pytest.raises(backend_client.BackendTimeout):
        _post(backend_client)

    assert post.call_count == 1


def test_http_error_response_is_not_sent_again_to_the_next_candidate(backend_client, monkeypatch):
    response = MagicMock(status_code=500)
    post = MagicMock(return_value=response)
    monkeypatch.setattr(backend_client.requests, "post", post)

    assert _post(backend_client) == (response, CANDIDATES[0])
    assert post.call_count == 1


@pytest.mark.parametrize("error", [requests.exceptions.ConnectionError("refused"), requests.exceptions.ConnectTimeout("no route")])
def test_unreachable_server_falls_back_to_the_next_candidate(backend_client, monkeypatch, error):
    response = MagicMock(status_code=200)
    post = MagicMock(side_effect=[error, response])
    monkeypatch.setattr(backend_client.requests, "post", post)

    assert _post(backend_client) == (response, CANDIDATES[1])


def _get(backend_client):
    return backend_client.get_with_failover(CANDIDATES, "/api/v1/ask/jobs/abc", {}, 10)


def test_get_returns_the_first_response_and_its_url_without_a_body(backend_client, monkeypatch):
    response = MagicMock(status_code=200)
    get = MagicMock(return_value=response)
    monkeypatch.setattr(backend_client.requests, "get", get)

    assert _get(backend_client) == (response, CANDIDATES[0])
    assert get.call_args.kwargs["json"] is None


def test_get_read_timeout_is_not_sent_again_to_the_next_candidate(backend_client, monkeypatch):
    get = MagicMock(side_effect=requests.exceptions.ReadTimeout("slow"))
    monkeypatch.setattr(backend_client.requests, "get", get)

    with pytest.raises(backend_client.BackendTimeout):
        _get(backend_client)

    assert get.call_count == 1


def test_get_unreachable_server_falls_back_to_the_next_candidate(backend_client, monkeypatch):
    response = MagicMock(status_code=200)
    get = MagicMock(side_effect=[requests.exceptions.ConnectionError("refused"), response])
    monkeypatch.setattr(backend_client.requests, "get", get)

    assert _get(backend_client) == (response, CANDIDATES[1])


def test_every_candidate_unreachable_raises_backend_unreachable(backend_client, monkeypatch):
    post = MagicMock(side_effect=requests.exceptions.ConnectionError("refused"))
    monkeypatch.setattr(backend_client.requests, "post", post)

    with pytest.raises(backend_client.BackendUnreachable):
        _post(backend_client)

    assert post.call_count == 2
