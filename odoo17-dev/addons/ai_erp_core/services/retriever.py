# -*- coding: utf-8 -*-
"""
retriever.py
============
Semantic retrieval layer.
Given a user query string, embeds it and searches both ChromaDB collections
(documents and code), returning ranked, deduplicated chunks ready for prompt
injection with their citation metadata.
"""
import logging
from typing import Any

_logger = logging.getLogger(__name__)


class RetrieverService:
    """
    Retrieve relevant chunks from ChromaDB for a given query.

    Parameters
    ----------
    config : ai.config recordset
    """

    def __init__(self, config):
        self.config = config
        self._ollama = None
        self._vstore = None

    def _get_ollama(self):
        if not self._ollama:
            from .ollama_client import OllamaClient
            self._ollama = OllamaClient(self.config)
        return self._ollama

    def _get_vstore(self):
        if not self._vstore:
            from .vector_store import VectorStoreService
            self._vstore = VectorStoreService(self.config)
        return self._vstore

    # ── Public API ──────────────────────────────────────────────────────────────

    def retrieve_documents(
        self, query: str, top_k: int | None = None
    ) -> list[dict[str, Any]]:
        """
        Search the documents collection (PDFs, wikis, tickets).

        Returns
        -------
        List of hit dicts with keys: document, metadata, score
        """
        return self._search(
            self.config.chromadb_collection_docs or 'erp_documents',
            query,
            top_k,
        )

    def retrieve_code(
        self, query: str, top_k: int | None = None
    ) -> list[dict[str, Any]]:
        """
        Search the code collection (Python/XML source files).

        Returns
        -------
        List of hit dicts with keys: document, metadata, score
        """
        return self._search(
            self.config.chromadb_collection_code or 'erp_code',
            query,
            top_k,
        )

    def retrieve_all(
        self, query: str, top_k: int | None = None
    ) -> dict[str, list[dict]]:
        """
        Search both collections and return results grouped by type.

        Returns
        -------
        {'docs': [...], 'code': [...]}
        """
        k = top_k or self.config.rag_top_k or 5
        doc_hits = []
        code_hits = []
        try:
            doc_hits = self.retrieve_documents(query, k)
        except Exception as exc:
            _logger.warning('Document retrieval failed: %s', exc)
        try:
            code_hits = self.retrieve_code(query, k)
        except Exception as exc:
            _logger.warning('Code retrieval failed: %s', exc)
        return {'docs': doc_hits, 'code': code_hits}

    # ── Prompt building helpers ─────────────────────────────────────────────────

    @staticmethod
    def hits_to_context_block(hits: list[dict], label: str = 'Sources') -> str:
        """
        Format retrieved chunks into a structured context block for the prompt.

        Each chunk is wrapped with citation markers that the LLM is expected
        to reference in its answer.

        Example output::

            === Sources ===
            [1] Source: manual_rh.pdf | Page: 3 | Score: 94.2%
            ---
            Le congé annuel est de 30 jours ouvrables...
            ---
        """
        if not hits:
            return ''
        parts = [f'=== {label} ===']
        for i, hit in enumerate(hits, start=1):
            meta = hit.get('metadata', {})
            source = meta.get('source', 'Inconnu')
            score_pct = round(hit.get('score', 0) * 100, 1)
            detail_parts = [f'Source: {source}']
            if 'page' in meta:
                detail_parts.append(f'Page: {meta["page"]}')
            if 'line_start' in meta:
                detail_parts.append(f'Lignes: {meta["line_start"]}-{meta["line_end"]}')
            detail_parts.append(f'Score: {score_pct}%')
            parts.append(f'\n[{i}] {" | ".join(detail_parts)}')
            parts.append('---')
            parts.append(hit.get('document', ''))
            parts.append('---')
        return '\n'.join(parts)

    @staticmethod
    def hits_to_citations(hits: list[dict]) -> list[dict]:
        """
        Convert raw hits to the citation format stored in ai.message.citations.
        """
        citations = []
        for hit in hits:
            meta = hit.get('metadata', {})
            cite: dict[str, Any] = {
                'source': meta.get('source', 'Inconnu'),
                'score': hit.get('score', 0.0),
            }
            if 'page' in meta:
                cite['page'] = meta['page']
            if 'line_start' in meta:
                cite['line_start'] = meta['line_start']
                cite['line_end'] = meta.get('line_end', meta['line_start'])
            if 'article_id' in meta:
                cite['article_id'] = meta['article_id']
            if 'ticket_id' in meta:
                cite['ticket_id'] = meta['ticket_id']
            citations.append(cite)
        return citations

    # ── Internal ────────────────────────────────────────────────────────────────

    def _search(
        self, collection_name: str, query: str, top_k: int | None
    ) -> list[dict]:
        k = top_k or self.config.rag_top_k or 5
        query_emb = self._get_ollama().embed(query)
        return self._get_vstore().search(collection_name, query_emb, top_k=k)
