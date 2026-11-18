from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.schemas import AssistantResponse, LLMResponse, SourceReference
from core.graph.graph_nodes import format_output, retrieve
from core.messages import GENERATION_ERROR_ANSWER, NO_SOURCE_ANSWER
from document_rag.generation.generate_node import generate, _parse_raw_json_answer
from document_rag.generation.generate_helpers import verify_used_sources


def test_generate_without_context_returns_no_source_answer():
    state = {'question': 'Où est le bureau ?', 'chat_history': [], 'retrieved_chunks': []}
    result = generate(state)
    assert result['response'].answer == NO_SOURCE_ANSWER
    assert result['response'].confidence == 0.0
    assert not result['response'].sources

def test_generation_failure_does_not_expose_the_exception_to_the_user():
    state = {'question': 'Où est le bureau ?', 'chat_history': [], 'retrieved_chunks': [{'document': 'd', 'source': 's'}]}
    with patch('document_rag.generation.generate_node.invoke_llm', side_effect=RuntimeError('secret-host:11434')):
        result = generate(state)
    assert result['response'].answer == GENERATION_ERROR_ANSWER


def test_retrieve_node_lets_a_backend_failure_reach_the_pipeline():
    with patch('core.graph.graph_nodes.quick_retrieve', side_effect=ConnectionError('embedding server unreachable')):
        with pytest.raises(ConnectionError):
            retrieve({'question': 'Comment déployer un module ?'})


def test_parse_raw_json_answer_extracts_answer_field():
    raw = '{"answer": "Réponse.", "sources": [], "confidence": 0.9}'
    assert _parse_raw_json_answer(raw) == 'Réponse.'


def test_parse_raw_json_answer_strips_markdown_fence():
    raw = '```json\n{"answer": "Réponse.", "confidence": 0.7}\n```'
    assert _parse_raw_json_answer(raw) == 'Réponse.'


def test_parse_raw_json_answer_rejects_unstructured_text():
    assert _parse_raw_json_answer('Réponse libre.') is None


@patch('document_rag.generation.generate_node._build_llm')
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


def _generate_with(chunks, used_sources):
    with patch('document_rag.generation.generate_node._build_llm') as build_llm:
        llm = build_llm.return_value
        llm.with_structured_output.return_value.invoke.return_value = LLMResponse(
            answer='Voici la réponse.', confidence=0.8, used_sources=used_sources)
        return generate({'question': 'q', 'chat_history': [], 'retrieved_chunks': chunks})['response']


SCAN = {'document': 'scan', 'metadata': {'source': 'scan.pdf', 'type': 'doc_pdf', 'ocr_quality': 'low'}}
WIKI = {'document': 'wiki', 'metadata': {'source': 'wiki.md', 'type': 'doc_wiki'}}


def test_a_cited_low_quality_scan_raises_the_ocr_warning():
    response = _generate_with([WIKI, SCAN], ['S2'])
    assert response.ocr_warning
    assert response.answer == 'Voici la réponse.'


def test_a_low_quality_scan_that_is_not_cited_does_not_raise_the_ocr_warning():
    assert not _generate_with([SCAN, WIKI], ['S2']).ocr_warning


def test_without_declared_sources_any_retrieved_low_quality_scan_raises_the_ocr_warning():
    assert _generate_with([WIKI, SCAN], []).ocr_warning
    assert not _generate_with([WIKI], []).ocr_warning


@patch('document_rag.generation.generate_node._build_llm')
def test_the_ocr_warning_survives_the_raw_invoke_fallback(mock_build_llm):
    llm = mock_build_llm.return_value
    llm.with_structured_output.return_value.invoke.side_effect = RuntimeError('structured output unavailable')
    llm.invoke.return_value = SimpleNamespace(content='Réponse libre.')
    state = {'question': 'q', 'chat_history': [], 'retrieved_chunks': [WIKI, SCAN]}
    assert generate(state)['response'].ocr_warning


def _source(title, source):
    return SourceReference(source=source, doc_type='pdf', title=title, snippet='')


def test_format_output_appends_source_links_to_the_answer():
    sources = [_source('Guide [v2]', 'https://drive.example/a'), _source('Note', 'https://drive.example/b')]
    state = {'response': AssistantResponse(answer='Voici la réponse.', confidence=0.8, sources=sources)}
    answer = format_output(state)['response'].answer
    assert answer == (
        'Voici la réponse.\n\n'
        'Sources: [Guide (v2)](https://drive.example/a), [Note](https://drive.example/b)'
    )


def test_format_output_skips_sources_without_a_web_link():
    state = {'response': AssistantResponse(answer='Voici la réponse.', confidence=0.8, sources=[_source('Local', 'docs/a.md')])}
    assert format_output(state)['response'].answer == 'Voici la réponse.'


def test_used_sources_deduplicate_same_document():
    alias_map = {
        'S1': {'document': 'Première section', 'metadata': {'source': 'wiki.md', 'type': 'wiki', 'title': 'Wiki'}},
        'S2': {'document': 'Deuxième section', 'metadata': {'source': 'wiki.md', 'type': 'wiki', 'title': 'Wiki'}},
    }
    result = verify_used_sources(['S1', 'S2'], alias_map)
    assert len(result) == 1
    assert result[0].snippet == 'Première section'
