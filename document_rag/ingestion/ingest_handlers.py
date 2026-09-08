"""
document_rag/ingestion/ingest_handlers.py

Re-exports for document and code ingestion handlers.
"""

from document_rag.ingestion.ingest_handlers_code import (
    ingest_code_dir,
    load_and_ingest_csv,
    load_and_ingest_js,
    load_and_ingest_python,
    load_and_ingest_xml,
)
from document_rag.ingestion.ingest_handlers_doc import (
    ingest_documents_dir,
    load_and_ingest_pdfs,
    load_and_ingest_wiki,
)

__all__ = [
    "load_and_ingest_pdfs",
    "load_and_ingest_wiki",
    "ingest_documents_dir",
    "load_and_ingest_python",
    "load_and_ingest_xml",
    "load_and_ingest_js",
    "load_and_ingest_csv",
    "ingest_code_dir",
]
