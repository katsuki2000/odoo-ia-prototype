# -*- coding: utf-8 -*-
"""
ingestion.py
============
Ingestion pipeline — converts raw content into text chunks, embeds them,
and stores them in ChromaDB.

Supported sources:
  1. PDF files      (via PyMuPDF / fitz, fallback to pdfminer)
  2. Odoo Knowledge articles (via XML-RPC)
  3. Helpdesk tickets (via Odoo ORM)
  4. Python source files
  5. XML source files

Every chunk's metadata includes:
  - source       : filename or article title
  - source_type  : pdf | wiki | ticket | code_python | code_xml
  - page         : page number (PDFs)
  - line_start   : first line in file (code)
  - line_end     : last line in file (code)
  - doc_id       : Odoo id of the ai.document record
  - odoo_version : always '17.0' for now
"""
import json
import logging
import os
import re
import uuid
from typing import Any

_logger = logging.getLogger(__name__)

# ── Optional dependency guards ──────────────────────────────────────────────────
try:
    import fitz  # PyMuPDF
    _FITZ_AVAILABLE = True
except ImportError:
    _FITZ_AVAILABLE = False
    _logger.info('ai_erp_core: PyMuPDF (fitz) not installed — PDF ingestion limited.')


class IngestionError(Exception):
    """Raised when an ingestion step fails unrecoverably."""


# ─────────────────────────────────────────────────────────────────────────────
# Text splitter (no LangChain dependency in this module — keep it lightweight)
# ─────────────────────────────────────────────────────────────────────────────

def _split_text(text: str, chunk_size: int = 512, overlap: int = 64) -> list[str]:
    """
    Split *text* into overlapping chunks by word count.

    Parameters
    ----------
    text       : raw text
    chunk_size : target number of words per chunk
    overlap    : number of words to repeat between consecutive chunks

    Returns
    -------
    List of text chunks.
    """
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = ' '.join(words[start:end])
        if chunk.strip():
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


def _split_code(
    text: str, chunk_size: int = 512, overlap: int = 64
) -> list[tuple[str, int, int]]:
    """
    Split *text* into overlapping chunks, tracking line numbers.

    Returns
    -------
    List of (chunk_text, line_start, line_end).
    """
    lines = text.splitlines(keepends=True)
    results = []
    i = 0
    while i < len(lines):
        chunk_lines = lines[i: i + chunk_size]
        chunk_text = ''.join(chunk_lines)
        if chunk_text.strip():
            results.append((chunk_text, i + 1, i + len(chunk_lines)))
        i += chunk_size - overlap
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Main service
# ─────────────────────────────────────────────────────────────────────────────

class IngestionService:
    """
    Orchestrates the full ingestion pipeline for one ai.document record.

    Parameters
    ----------
    env : Odoo environment
    """

    def __init__(self, env):
        self.env = env
        self._config = None
        self._ollama = None
        self._vstore = None

    def _get_config(self):
        if not self._config:
            self._config = self.env['ai.config'].get_active_config()
            if not self._config:
                raise IngestionError('Aucune configuration IA active trouvée.')
        return self._config

    def _get_ollama(self):
        if not self._ollama:
            from .ollama_client import OllamaClient
            self._ollama = OllamaClient(self._get_config())
        return self._ollama

    def _get_vstore(self):
        if not self._vstore:
            from .vector_store import VectorStoreService
            self._vstore = VectorStoreService(self._get_config())
        return self._vstore

    # ── Public entry point ──────────────────────────────────────────────────────

    def ingest_document(self, doc_record) -> dict[str, Any]:
        """
        Full ingestion pipeline for a single ai.document record.

        Returns
        -------
        dict with 'chunk_count', 'chroma_ids_json', 'collection_name'.
        """
        dtype = doc_record.doc_type
        _logger.info('Starting ingestion of doc %s (type=%s)', doc_record.id, dtype)

        if dtype == 'pdf':
            return self._ingest_pdf(doc_record)
        elif dtype == 'wiki':
            return self._ingest_wiki(doc_record)
        elif dtype == 'ticket':
            return self._ingest_ticket(doc_record)
        elif dtype in ('code_python', 'code_xml'):
            return self._ingest_code(doc_record)
        else:
            raise IngestionError(f'Type de document non supporté : {dtype}')

    # ── PDF ─────────────────────────────────────────────────────────────────────

    def _ingest_pdf(self, doc) -> dict:
        config = self._get_config()
        collection = config.chromadb_collection_docs

        # Retrieve raw bytes from ir.attachment or filesystem path
        pages_text: list[tuple[int, str]] = []

        if doc.attachment_id:
            raw = doc.attachment_id._file_read(doc.attachment_id.store_fname)
            if not _FITZ_AVAILABLE:
                raise IngestionError(
                    'PyMuPDF (fitz) requis pour lire les PDFs. '
                    'Installez-le dans le conteneur Odoo : pip install pymupdf'
                )
            pdf = fitz.open(stream=raw, filetype='pdf')
            for page_num, page in enumerate(pdf, start=1):
                text = page.get_text()
                if text.strip():
                    pages_text.append((page_num, text))
            pdf.close()

        elif doc.source_path and os.path.isfile(doc.source_path):
            if not _FITZ_AVAILABLE:
                raise IngestionError('PyMuPDF (fitz) requis pour lire les PDFs.')
            pdf = fitz.open(doc.source_path)
            for page_num, page in enumerate(pdf, start=1):
                text = page.get_text()
                if text.strip():
                    pages_text.append((page_num, text))
            pdf.close()
        else:
            raise IngestionError(
                'PDF : ni pièce jointe ni chemin fichier valide trouvé.'
            )

        # Build chunks with page-level metadata
        all_ids, all_embeddings, all_docs, all_metas = [], [], [], []
        for page_num, page_text in pages_text:
            chunks = _split_text(page_text, config.chunk_size, config.chunk_overlap)
            for idx, chunk in enumerate(chunks):
                chunk_id = f'pdf-{doc.id}-p{page_num}-c{idx}'
                emb = self._get_ollama().embed(chunk)
                all_ids.append(chunk_id)
                all_embeddings.append(emb)
                all_docs.append(chunk)
                all_metas.append({
                    'source': doc.name,
                    'source_type': 'pdf',
                    'page': page_num,
                    'doc_id': str(doc.id),
                    'odoo_version': '17.0',
                })

        self._get_vstore().upsert_chunks(
            collection, all_ids, all_embeddings, all_docs, all_metas
        )
        return {
            'chunk_count': len(all_ids),
            'chroma_ids_json': json.dumps(all_ids),
            'collection_name': collection,
        }

    # ── Odoo Knowledge wiki ─────────────────────────────────────────────────────

    def _ingest_wiki(self, doc) -> dict:
        config = self._get_config()
        collection = config.chromadb_collection_docs

        # Knowledge articles live in knowledge.article (Odoo 17 enterprise)
        # or as HTML body in document.page (community). We try both.
        article_model = (
            'knowledge.article'
            if 'knowledge.article' in self.env
            else 'document.page'
        )
        article_id = int(doc.source_ref or 0)
        if not article_id:
            raise IngestionError('ID d\'article Knowledge manquant dans source_ref.')

        article = self.env[article_model].browse(article_id)
        if not article.exists():
            raise IngestionError(f'Article {article_id} introuvable dans {article_model}.')

        # Extract plain text from HTML body
        body_html = getattr(article, 'body', '') or getattr(article, 'content', '') or ''
        plain_text = re.sub(r'<[^>]+>', ' ', body_html)
        plain_text = re.sub(r'\s+', ' ', plain_text).strip()

        if not plain_text:
            raise IngestionError('Article vide — rien à indexer.')

        chunks = _split_text(plain_text, config.chunk_size, config.chunk_overlap)
        all_ids, all_embeddings, all_docs, all_metas = [], [], [], []
        for idx, chunk in enumerate(chunks):
            chunk_id = f'wiki-{doc.id}-c{idx}'
            emb = self._get_ollama().embed(chunk)
            all_ids.append(chunk_id)
            all_embeddings.append(emb)
            all_docs.append(chunk)
            all_metas.append({
                'source': doc.name,
                'source_type': 'wiki',
                'article_id': str(article_id),
                'doc_id': str(doc.id),
                'odoo_version': '17.0',
            })

        self._get_vstore().upsert_chunks(
            collection, all_ids, all_embeddings, all_docs, all_metas
        )
        return {
            'chunk_count': len(all_ids),
            'chroma_ids_json': json.dumps(all_ids),
            'collection_name': collection,
        }

    # ── Helpdesk ticket ─────────────────────────────────────────────────────────

    def _ingest_ticket(self, doc) -> dict:
        config = self._get_config()
        collection = config.chromadb_collection_docs

        ticket_id = int(doc.source_ref or 0)
        if not ticket_id:
            raise IngestionError('ID de ticket Helpdesk manquant dans source_ref.')

        if 'helpdesk.ticket' not in self.env:
            raise IngestionError(
                'Le module Helpdesk n\'est pas installé sur cette instance Odoo.'
            )

        ticket = self.env['helpdesk.ticket'].browse(ticket_id)
        if not ticket.exists():
            raise IngestionError(f'Ticket {ticket_id} introuvable.')

        # Combine name + description + chatter messages
        text_parts = [ticket.name or '']
        if ticket.description:
            text_parts.append(re.sub(r'<[^>]+>', ' ', ticket.description))

        # Include public chatter messages
        messages = self.env['mail.message'].search([
            ('res_id', '=', ticket_id),
            ('model', '=', 'helpdesk.ticket'),
            ('message_type', 'in', ['comment', 'email']),
        ], order='date asc')
        for msg in messages:
            body = re.sub(r'<[^>]+>', ' ', msg.body or '')
            if body.strip():
                text_parts.append(body)

        full_text = ' '.join(text_parts)
        full_text = re.sub(r'\s+', ' ', full_text).strip()
        if not full_text:
            raise IngestionError('Ticket vide — rien à indexer.')

        chunks = _split_text(full_text, config.chunk_size, config.chunk_overlap)
        all_ids, all_embeddings, all_docs, all_metas = [], [], [], []
        for idx, chunk in enumerate(chunks):
            chunk_id = f'ticket-{doc.id}-c{idx}'
            emb = self._get_ollama().embed(chunk)
            all_ids.append(chunk_id)
            all_embeddings.append(emb)
            all_docs.append(chunk)
            all_metas.append({
                'source': ticket.name,
                'source_type': 'ticket',
                'ticket_id': str(ticket_id),
                'doc_id': str(doc.id),
                'odoo_version': '17.0',
            })

        self._get_vstore().upsert_chunks(
            collection, all_ids, all_embeddings, all_docs, all_metas
        )
        return {
            'chunk_count': len(all_ids),
            'chroma_ids_json': json.dumps(all_ids),
            'collection_name': collection,
        }

    # ── Source code ─────────────────────────────────────────────────────────────

    def _ingest_code(self, doc) -> dict:
        config = self._get_config()
        collection = config.chromadb_collection_code

        path = doc.source_path
        if not path or not os.path.isfile(path):
            raise IngestionError(f'Fichier source introuvable : {path}')

        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()

        if not content.strip():
            raise IngestionError(f'Fichier vide : {path}')

        chunks_with_lines = _split_code(content, chunk_size=80, overlap=10)
        # chunk_size in lines for code (not words)

        all_ids, all_embeddings, all_docs, all_metas = [], [], [], []
        for idx, (chunk_text, line_start, line_end) in enumerate(chunks_with_lines):
            chunk_id = f'code-{doc.id}-c{idx}'
            emb = self._get_ollama().embed(chunk_text)
            all_ids.append(chunk_id)
            all_embeddings.append(emb)
            all_docs.append(chunk_text)
            all_metas.append({
                'source': path,
                'source_type': doc.doc_type,
                'line_start': line_start,
                'line_end': line_end,
                'doc_id': str(doc.id),
                'odoo_version': '17.0',
            })

        self._get_vstore().upsert_chunks(
            collection, all_ids, all_embeddings, all_docs, all_metas
        )
        return {
            'chunk_count': len(all_ids),
            'chroma_ids_json': json.dumps(all_ids),
            'collection_name': collection,
        }

    # ── Batch code ingestion from directory ────────────────────────────────────

    def ingest_code_directory(self, directory: str) -> dict[str, Any]:
        """
        Walk *directory*, create ai.document records and ingest all .py and .xml files.

        Returns a summary dict.
        """
        if not os.path.isdir(directory):
            raise IngestionError(f'Répertoire introuvable : {directory}')

        AiDoc = self.env['ai.document']
        total_chunks = 0
        total_files = 0
        errors = []

        for root, _dirs, files in os.walk(directory):
            # Skip __pycache__ and .git
            if any(part.startswith('.') or part == '__pycache__' for part in root.split(os.sep)):
                continue
            for filename in files:
                ext = os.path.splitext(filename)[1].lower()
                if ext not in ('.py', '.xml'):
                    continue
                filepath = os.path.join(root, filename)
                doc_type = 'code_python' if ext == '.py' else 'code_xml'

                # Create or retrieve existing ai.document record
                existing = AiDoc.search([('source_path', '=', filepath)], limit=1)
                if existing:
                    doc = existing
                    doc.write({'ingestion_status': 'processing'})
                else:
                    doc = AiDoc.create({
                        'name': os.path.relpath(filepath, directory),
                        'doc_type': doc_type,
                        'source_path': filepath,
                        'ingestion_status': 'processing',
                    })

                try:
                    result = self._ingest_code(doc)
                    doc.write({
                        'ingestion_status': 'done',
                        'chunk_count': result['chunk_count'],
                        'chroma_ids': result['chroma_ids_json'],
                        'collection_name': result['collection_name'],
                    })
                    total_chunks += result['chunk_count']
                    total_files += 1
                except Exception as exc:
                    _logger.warning('Code ingestion failed for %s: %s', filepath, exc)
                    doc.write({'ingestion_status': 'error', 'ingestion_error': str(exc)})
                    errors.append({'file': filepath, 'error': str(exc)})

        return {
            'total_files': total_files,
            'total_chunks': total_chunks,
            'errors': errors,
        }
