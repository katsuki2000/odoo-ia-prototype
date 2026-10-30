import json
import logging

from config.settings import QUESTION_PREVIEW_CHARS
from document_rag.vectorstore import search


def test_retrieval_trace_logs_only_a_question_preview(monkeypatch, caplog):
    sensitive_suffix = "private-term-that-must-not-be-logged"
    query = ("What is the internal procedure? " * 5) + sensitive_suffix
    monkeypatch.setattr(
        search,
        "hybrid_search",
        lambda **kwargs: [
            {
                "id": "chunk-1",
                "document": "A retrieved document paragraph.",
                "metadata": {"source": "procedure.md", "type": "doc_wiki"},
                "score": 0.9,
            }
        ],
    )

    with caplog.at_level(logging.INFO, logger="document_rag.vectorstore.search"):
        search.retrieve(query, chroma_manager=object(), bm25_index=object(), top_k=1)

    trace = next(
        record.getMessage()
        for record in caplog.records
        if '"event": "retrieval_trace"' in record.getMessage()
    )
    payload = json.loads(trace)
    assert payload["question"] == query[:QUESTION_PREVIEW_CHARS]
    assert "question" not in payload
    assert sensitive_suffix not in trace
