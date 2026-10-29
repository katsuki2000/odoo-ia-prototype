"""
tests/test_e2e_watcher_rag.py
End-to-end validation: drop a new document into monitored directory, verify incremental reindex
indexes it and the assistant/retrieval pipeline answers correctly.
Delete the document, verify incremental reindex removes it and the assistant says it doesn't know / no results.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from document_rag.ingestion.incremental import reindex_if_changed
from document_rag.vectorstore.chroma_manager import ChromaManager
from document_rag.vectorstore.search import retrieve
from core.graph.graph import query_graph
from core.schemas import AssistantResponse, LLMResponse


@pytest.mark.integration
def test_e2e_live_add_delete_query_cycle():
    """
    Simulate the end-to-end add/delete cycle monitored by watcher / incremental scanner:
    1. Drop new document into monitored `docs/` folder.
    2. Run ingestion check (`reindex_if_changed`).
    3. Verify retrieval finds the new document content.
    4. Delete the document.
    5. Run ingestion check (`reindex_if_changed`).
    6. Verify retrieval returns no matches and assistant reports no source.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        temp_path = Path(temp_dir)
        docs_dir = temp_path / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        db_path = temp_path / "chroma_e2e"

        manager = ChromaManager(db_path=db_path, collection_name="e2e_test_coll")

        secret_filename = "doc_secret_katsuki.txt"
        secret_path = docs_dir / secret_filename
        secret_content = "Le code secret de validation Odoo RAG pour le projet Katsuki est ALPHA-9988-OMEGA."

        # ── Step 1: Drop new document into docs/ and ingest ────────────────
        secret_path.write_text(secret_content, encoding="utf-8")
        reindex_if_changed([docs_dir], docs_manager=manager, chunk_size=512, chunk_overlap=50)

        stats = manager.get_stats()
        assert stats.get("total_chunks", 0) > 0

        # ── Step 2: Verify retrieve() finds the document ───────────────────
        results = retrieve("Quel est le code secret Katsuki ?", top_k=3, chroma_manager=manager)
        assert len(results) > 0
        assert any("ALPHA-9988-OMEGA" in r["document"] for r in results)
        assert any(secret_filename in r["metadata"].get("source", "") for r in results)

        # ── Step 3: Verify query_graph answers using this document ─────────
        with patch("core.graph.graph_nodes.get_retriever") as mock_get_retriever, \
             patch("document_rag.generate_node._build_llm") as mock_build_llm:

            mock_retriever = MagicMock()
            mock_bm25 = MagicMock()
            mock_get_retriever.return_value = (mock_retriever, mock_bm25)
            
            # Patch search_retrieve inside graph to use our real e2e manager
            with patch("core.graph.graph_nodes.search_retrieve", side_effect=lambda query, top_k, chroma_manager=None, bm25_index=None, where=None: retrieve(query, top_k=top_k, chroma_manager=manager, where=where)):
                mock_llm_instance = MagicMock()
                mock_build_llm.return_value = mock_llm_instance
                mock_structured_llm = MagicMock()
                mock_llm_instance.with_structured_output.return_value = mock_structured_llm
                
                mock_structured_llm.invoke.return_value = LLMResponse(
                    answer="Le code secret de validation Odoo RAG est ALPHA-9988-OMEGA.",
                    confidence=0.98,
                    used_sources=["S1"],
                )
                
                # The documentary branch must be chosen explicitly. Without source_mode the router
                # calls a real LLM (core/routing/source_selection.py, since 132f0fb), which makes
                # this test non-deterministic: source_mode='documentation' is the UI source option.
                response = query_graph("Selon la documentation, quel est le code secret de validation ?", source_mode="documentation")
                assert isinstance(response, AssistantResponse)
                assert "ALPHA-9988-OMEGA" in response.answer
                assert len(response.sources) > 0
                assert any(secret_filename in s.source for s in response.sources)

        # ── Step 4: Delete the file and reindex ────────────────────────────
        secret_path.unlink()
        assert not secret_path.exists()

        reindex_if_changed([docs_dir], docs_manager=manager, chunk_size=512, chunk_overlap=50)

        # ── Step 5: Verify retrieve() no longer finds the document ─────────
        results_after_delete = retrieve("Quel est le code secret Katsuki ?", top_k=3, chroma_manager=manager)
        assert not any("ALPHA-9988-OMEGA" in r["document"] for r in results_after_delete)

        # ── Step 6: Verify query_graph falls back safely when document is gone
        with patch("core.graph.graph_nodes.get_retriever") as mock_get_retriever:

            mock_get_retriever.return_value = (MagicMock(), MagicMock())
            with patch("core.graph.graph_nodes.search_retrieve", side_effect=lambda query, top_k, chroma_manager=None, bm25_index=None, where=None: retrieve(query, top_k=top_k, chroma_manager=manager, where=where)):
                # Same explicit source choice as Step 3 above (no routing LLM call).
                response_after_delete = query_graph("Selon la documentation, quel est le code secret Katsuki ?", source_mode="documentation")
                assert len(response_after_delete.sources) == 0
                assert response_after_delete.confidence == 0.0
                assert "pas de source fiable" in response_after_delete.answer.lower() or "ne sais pas" in response_after_delete.answer.lower()

        try:
            manager.delete_collection()
        except Exception:
            pass
