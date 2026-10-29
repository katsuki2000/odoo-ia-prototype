"""Unit tests for the Ollama chat client factory."""

import pytest
from unittest.mock import patch

from langchain_openai import ChatOpenAI

from core.llm.llm_client import get_chat_llm


def test_get_chat_llm_explicit_endpoint():
    llm = get_chat_llm(base_url="http://127.0.0.1:11434/v1", model="llama3.1", api_key="ollama")
    assert isinstance(llm, ChatOpenAI)
    assert "127.0.0.1:11434" in str(llm.openai_api_base)
    assert llm.model_name == "llama3.1"


def test_get_chat_llm_uses_configured_server():
    with patch("core.llm.llm_client.LLM_BASE_URL", "http://127.0.0.1:8000/v1"), \
         patch("core.llm.llm_client.LLM_MODEL", "meta-llama/Llama-3-8b-instruct"):
        llm = get_chat_llm()
        assert "127.0.0.1:8000" in str(llm.openai_api_base)
        assert llm.model_name == "meta-llama/Llama-3-8b-instruct"


def test_get_chat_llm_without_server_raises_instead_of_falling_back_to_openai():
    with patch("core.llm.llm_client.LLM_BASE_URL", ""), pytest.raises(ValueError, match="No inference server configured"):
        get_chat_llm()


def test_document_rag_generate_uses_configured_llm():
    from document_rag.generate_node import _build_llm
    with patch("core.llm.llm_client.LLM_BASE_URL", "http://localhost:11434/v1"), \
         patch("core.llm.llm_client.LLM_MODEL", "llama3.1"):
        assert isinstance(_build_llm(temperature=0.0), ChatOpenAI)


def test_erp_data_orm_helpers_uses_configured_llm():
    from erp_data.orm_agent_helpers import _build_llm
    with patch("core.llm.llm_client.LLM_BASE_URL", "http://localhost:11434/v1"), \
         patch("core.llm.llm_client.LLM_MODEL", "llama3.1"):
        assert isinstance(_build_llm(temperature=0.0), ChatOpenAI)


def test_health_check_v1_never_exposes_the_llm_endpoint():
    from api.routes_system import health_check_v1
    with patch("config.settings.LLM_BASE_URL", "http://localhost:11434/v1"), \
         patch("document_rag.vectorstore.chroma_manager.ChromaManager") as mock_chroma, \
         patch("erp_data.odoo_connector.OdooConnector") as mock_odoo:
        mock_chroma.return_value.client.heartbeat.return_value = 1
        mock_odoo.return_value.authenticate.return_value = 2

        status = health_check_v1()
        assert status["status"] == "ok"
        assert status["services"]["llm"] == "not checked"
        assert "localhost:11434" not in str(status)
