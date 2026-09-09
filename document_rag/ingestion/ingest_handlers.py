"""
document_rag/ingestion/ingest_handlers.py

Re-exports for document ingestion handlers.
"""

from document_rag.ingestion.ingest_handlers_doc import (
    ingest_documents_dir,
    load_and_ingest_pdfs,
    load_and_ingest_wiki,
)

__all__ = [
    "load_and_ingest_pdfs",
    "load_and_ingest_wiki",
    "ingest_documents_dir",
]
