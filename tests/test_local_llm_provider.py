"""Unit tests for local LLM migration and provider abstraction."""

import os
import pytest
from unittest.mock import patch, MagicMock

from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

from core.llm.llm_client import get_chat_llm


def test_get_chat_llm_groq_default():
    """Verify provider='groq' instantiates ChatGroq."""
    llm = get_chat_llm(provider="groq")
    assert isinstance(llm, ChatGroq)


def test_get_chat_llm_local_provider():
    """Verify provider='local' instantiates ChatOpenAI with local endpoint configuration."""
    llm = get_chat_llm(
        provider="local",
        base_url="http://localhost:11434/v1",
        model="llama3.1",
        api_key="ollama",
    )
    assert isinstance(llm, ChatOpenAI)
    assert "localhost:11434" in str(llm.openai_api_base)
    assert llm.model_name == "llama3.1"


def test_get_chat_llm_synonym_providers():
    """Verify synonyms 'ollama', 'vllm', 'openai_compatible' instantiate ChatOpenAI."""
    for p in ("ollama", "vllm", "openai_compatible", "lmstudio", "llamacpp"):
        llm = get_chat_llm(provider=p)
        assert isinstance(llm, ChatOpenAI), f"Failed for provider {p}"


def test_get_chat_llm_openrouter_provider():
    """Verify provider='openrouter' instantiates ChatOpenAI."""
    llm = get_chat_llm(provider="openrouter", api_key="sk-or-test")
    assert isinstance(llm, ChatOpenAI)
    assert "openrouter.ai" in str(llm.openai_api_base)


def test_get_chat_llm_unknown_provider_raises():
    """Verify unknown provider raises clear ValueError."""
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        get_chat_llm(provider="unsupported_provider")


def test_get_chat_llm_respects_env_switch():
    """Verify switching LLM_PROVIDER to 'local' via settings routes get_chat_llm to ChatOpenAI."""
    with patch("core.llm.llm_client.LLM_PROVIDER", "local"), \
         patch("core.llm.llm_client.LOCAL_LLM_BASE_URL", "http://127.0.0.1:8000/v1"), \
         patch("core.llm.llm_client.LOCAL_LLM_MODEL", "meta-llama/Llama-3-8b-instruct"):
        llm = get_chat_llm()
        assert isinstance(llm, ChatOpenAI)
        assert "127.0.0.1:8000" in str(llm.openai_api_base)
        assert llm.model_name == "meta-llama/Llama-3-8b-instruct"


def test_document_rag_generate_uses_local_llm():
    """Verify document_rag generate node uses get_chat_llm and produces valid response with local LLM."""
    from document_rag.generate_node import _build_groq_llm
    with patch("core.llm.llm_client.LLM_PROVIDER", "local"), \
         patch("core.llm.llm_client.LOCAL_LLM_BASE_URL", "http://localhost:11434/v1"), \
         patch("core.llm.llm_client.LOCAL_LLM_MODEL", "llama3.1"):
        llm = _build_groq_llm(temperature=0.0)
        assert isinstance(llm, ChatOpenAI)


def test_erp_data_orm_helpers_uses_local_llm():
    """Verify erp_data orm_agent_helpers uses get_chat_llm with local provider."""
    from erp_data.orm_agent_helpers import _build_groq_llm
    with patch("core.llm.llm_client.LLM_PROVIDER", "local"), \
         patch("core.llm.llm_client.LOCAL_LLM_BASE_URL", "http://localhost:11434/v1"), \
         patch("core.llm.llm_client.LOCAL_LLM_MODEL", "llama3.1"):
        llm = _build_groq_llm(temperature=0.0)
        assert isinstance(llm, ChatOpenAI)


def test_health_check_v1_local_provider_healthy():
    """Verify health check returns healthy status without Groq API key when LLM_PROVIDER is local."""
    from api.routes_system import health_check_v1
    with patch("config.settings.LLM_PROVIDER", "local"), \
         patch("config.settings.LOCAL_LLM_BASE_URL", "http://localhost:11434/v1"), \
         patch("document_rag.vectorstore.chroma_manager.get_chroma_client") as mock_chroma, \
         patch("erp_data.odoo_connector.OdooConnector") as mock_odoo:
        mock_chroma.return_value.heartbeat.return_value = 1
        mock_odoo.return_value.authenticate.return_value = 2

        status = health_check_v1()
        assert status["status"] == "ok"
        assert "local" in status["services"]["llm"]
        assert "local" in status["services"]["groq"]


def test_rate_limit_spacing_skipped_for_local():
    """Verify invoke_with_rate_limit does not sleep 5s when provider is local."""
    from core.llm.llm_client import _get_min_interval
    with patch("core.llm.llm_client.LLM_PROVIDER", "local"):
        assert _get_min_interval() == 0.0

    with patch("core.llm.llm_client.LLM_PROVIDER", "groq"):
        assert _get_min_interval() == 5.0

