import pytest

import config.settings as settings
import core.llm.llm_client as llmClient
from core.evaluation import ollama_server
from core.evaluation.preflight import BackendUnavailable


@pytest.mark.parametrize("model, marker", [("qwen3:8b", "/no_think"), ("QWEN3:30b-a3b", "/no_think"), ("gpt-oss:20b", "")])
def test_model_override_replaces_then_restores_settings(model, marker):
    before = (settings.LLM_MODEL, settings.LLM_NO_THINK_MARKER, llmClient.LLM_MODEL, llmClient.LLM_NO_THINK_MARKER)
    with ollama_server.model_override(model):
        assert (settings.LLM_MODEL, llmClient.LLM_MODEL) == (model, model)
        assert (settings.LLM_NO_THINK_MARKER, llmClient.LLM_NO_THINK_MARKER) == (marker, marker)
        assert llmClient.with_no_think("prompt").endswith(marker or "prompt")
    assert (settings.LLM_MODEL, settings.LLM_NO_THINK_MARKER, llmClient.LLM_MODEL, llmClient.LLM_NO_THINK_MARKER) == before


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
    keepAlives = {payload["model"]: payload["keep_alive"] for _, path, payload in calls if path == "/api/generate"}
    assert keepAlives == {"old:7b": 0, "new:14b": -1}
    assert info == {"vram_fraction": 0.75, "context_length": 4096}


def test_prepare_server_refuses_a_model_without_tool_support(monkeypatch):
    calls = _fake_server(monkeypatch, ["completion"], [])
    with pytest.raises(BackendUnavailable, match="tool support"):
        ollama_server.prepare_server("plain:7b")
    assert not [call for call in calls if call[1] == "/api/generate"]
