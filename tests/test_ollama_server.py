import pytest

import config.settings as settings
from core.llm import llm_client
from core.evaluation import ollama_server
from core.evaluation.preflight import BackendUnavailable


@pytest.mark.parametrize("model", ["qwen3:8b", "gpt-oss:20b"])
def test_model_override_replaces_then_restores_settings(model):
    before = (settings.LLM_MODEL, llm_client.LLM_MODEL)
    with ollama_server.model_override(model):
        assert (settings.LLM_MODEL, llm_client.LLM_MODEL) == (model, model)
    assert (settings.LLM_MODEL, llm_client.LLM_MODEL) == before


def _fake_server(monkeypatch, capabilities, loaded):
    calls = []

    def server_call(method, path, payload=None):
        calls.append((method, path, payload))
        if path == "/api/show":
            return {"capabilities": capabilities}
        if path == "/api/ps":
            return {"models": loaded}
        return {}

    monkeypatch.setattr(ollama_server, "server_call", server_call)
    return calls


def test_prepare_server_unloads_other_chat_models_and_reports_vram(monkeypatch):
    loaded = [
        {"name": "old:7b", "size": 10, "size_vram": 10},
        {"name": settings.EMBEDDING_MODEL, "size": 5, "size_vram": 5},
        {"name": "new:14b", "size": 20, "size_vram": 15, "context_length": 4096},
    ]
    calls = _fake_server(monkeypatch, ["completion", "tools"], loaded)
    info = ollama_server.prepare_server("new:14b")
    keep_alives = {payload["model"]: payload["keep_alive"] for _, path, payload in calls if path == "/api/generate"}
    assert keep_alives == {"old:7b": 0, "new:14b": -1}
    assert info == {"vram_fraction": 0.75, "context_length": 4096}


def test_prepare_server_refuses_a_model_without_tool_support(monkeypatch):
    calls = _fake_server(monkeypatch, ["completion"], [])
    with pytest.raises(BackendUnavailable, match="tool support"):
        ollama_server.prepare_server("plain:7b")
    assert not [call for call in calls if call[1] == "/api/generate"]
