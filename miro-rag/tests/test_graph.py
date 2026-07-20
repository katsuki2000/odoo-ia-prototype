import pytest
from unittest.mock import patch, MagicMock

from rag.schemas import AssistantResponse, LLMResponse
from rag.graph import query_graph, generate, format_output

# 1. Test fallback when no context is found
def test_generate_fallback():
    state = {
        "question": "Où est le bureau ?",
        "chat_history": [],
        "retrieved_chunks": []
    }
    result = generate(state)
    assert result["response"].answer == "Je n'ai pas de source fiable pour répondre à cette question."
    assert result["response"].confidence == 0.0
    assert len(result["response"].sources) == 0


def test_generate_out_of_scope_refuses_before_llm():
    state = {
        "question": "Raconte-moi une blague sur les ERP.",
        "chat_history": [],
        "retrieved_chunks": [
            {"document": "Odoo ERP context", "metadata": {"source": "wiki.txt"}}
        ],
    }
    result = generate(state)
    assert "Cette question ne fait pas partie de mon périmètre" in result["response"].answer
    assert result["response"].confidence == 0.0
    assert len(result["response"].sources) == 0


# 2. Test OCR warning injection
def test_format_output_ocr_warning():
    state = {
        "response": AssistantResponse(answer="Voici la réponse.", confidence=0.8, sources=[]),
        "retrieved_chunks": [
            {"document": "test doc", "metadata": {"source": "scan.pdf", "ocr_quality": "low", "type": "pdf"}}
        ]
    }
    result = format_output(state)
    assert result["response"].ocr_warning is True
    assert "qualité de lecture est limitée" in result["response"].answer
    assert len(result["response"].sources) == 1
    assert result["response"].sources[0].source == "scan.pdf"

# 3. Test format output WITHOUT OCR warning
def test_format_output_clean():
    state = {
        "response": AssistantResponse(answer="Voici la réponse.", confidence=0.8, sources=[]),
        "retrieved_chunks": [
            {"document": "test doc", "metadata": {"source": "wiki.md", "type": "wiki"}}
        ]
    }
    result = format_output(state)
    assert result["response"].ocr_warning is False
    assert "qualité de lecture est limitée" not in result["response"].answer

# 4. Test full query graph with mocked LLM and retriever
@patch('rag.graph.ChatOllama')
@patch('rag.graph.get_retriever')
@patch('rag.graph.search_retrieve')
def test_query_graph_mocked(mock_search_retrieve, mock_get_retriever, mock_chat_ollama):
    # Mock Retriever
    mock_get_retriever.return_value = (MagicMock(), MagicMock())
    mock_search_retrieve.return_value = [
        {"document": "Facture = Nouveau", "metadata": {"source": "facture.md"}}
    ]
    
    # Mock LLM
    mock_llm_instance = MagicMock()
    mock_chat_ollama.return_value = mock_llm_instance
    mock_structured_llm = MagicMock()
    mock_llm_instance.with_structured_output.return_value = mock_structured_llm
    
    mock_structured_llm.invoke.return_value = LLMResponse(
        answer="Pour créer une facture, cliquez sur Nouveau.",
        confidence=0.95
    )
    
    response = query_graph("Comment créer une facture ?")
    
    assert isinstance(response, AssistantResponse)
    assert response.confidence == 0.95
    assert response.ocr_warning is False
    assert len(response.sources) == 1
    assert response.sources[0].source == "facture.md"
