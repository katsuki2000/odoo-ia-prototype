from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.schemas import AssistantResponse
from core.graph.graph_nodes import format_output
from document_rag.generate_node import generate, _parse_raw_json_answer
from document_rag.generate_helpers import verify_used_sources


def test_generate_without_context_returns_no_source_answer():
    state = {'question': 'Où est le bureau ?', 'chat_history': [], 'retrieved_chunks': []}
    result = generate(state)
    assert result['response'].answer == "Je n'ai pas de source fiable pour répondre à cette question."
    assert result['response'].confidence == 0.0
    assert not result['response'].sources


def test_generate_refuses_out_of_scope_before_calling_llm():
    state = {
        'question': 'Raconte-moi une blague sur les ERP.',
        'chat_history': [],
        'retrieved_chunks': [{'document': 'Odoo ERP context', 'metadata': {'source': 'wiki.txt'}}],
    }
    result = generate(state)
    assert 'Cette question ne fait pas partie de mon périmètre' in result['response'].answer
    assert result['response'].confidence == 0.0
    assert not result['response'].sources


def test_parse_raw_json_answer_extracts_answer_field():
    raw = '{"answer": "Réponse.", "sources": [], "confidence": 0.9}'
    assert _parse_raw_json_answer(raw) == 'Réponse.'


def test_parse_raw_json_answer_strips_markdown_fence():
    raw = '```json\n{"answer": "Réponse.", "confidence": 0.7}\n```'
    assert _parse_raw_json_answer(raw) == 'Réponse.'


def test_parse_raw_json_answer_rejects_unstructured_text():
    assert _parse_raw_json_answer('Réponse libre.') is None


@patch('document_rag.generate_node._build_llm')
def test_raw_invoke_response_is_parsed_after_structured_call_fails(mock_build_llm):
    llm = MagicMock()
    mock_build_llm.return_value = llm
    llm.with_structured_output.return_value.invoke.side_effect = RuntimeError('structured output unavailable')
    llm.invoke.return_value = SimpleNamespace(
        content='{"answer": "Réponse issue des observations.", "sources": [], "confidence": 0.8}'
    )
    state = {
        'question': 'Pourquoi le montant est caché ?',
        'chat_history': [],
        'retrieved_chunks': [{'document': 'context', 'metadata': {'source': 'rule.xml'}}],
    }
    result = generate(state)
    assert result['response'].answer == 'Réponse issue des observations.'


def test_format_output_without_ocr_warning():
    state = {
        'response': AssistantResponse(answer='Voici la réponse.', confidence=0.8, sources=[]),
        'retrieved_chunks': [{'document': 'test doc', 'metadata': {'source': 'wiki.md', 'type': 'wiki'}}],
    }
    result = format_output(state)
    assert not result['response'].ocr_warning
    assert 'qualité de lecture est limitée' not in result['response'].answer


def test_used_sources_deduplicate_same_document():
    aliasMap = {
        'S1': {'document': 'Première section', 'metadata': {'source': 'wiki.md', 'type': 'wiki', 'title': 'Wiki'}},
        'S2': {'document': 'Deuxième section', 'metadata': {'source': 'wiki.md', 'type': 'wiki', 'title': 'Wiki'}},
    }
    result = verify_used_sources(['S1', 'S2'], aliasMap)
    assert len(result) == 1
    assert result[0].snippet == 'Première section'
