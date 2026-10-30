"""Load supported document formats into chunks and metadata."""

from pathlib import Path
from typing import Any

from config.settings import RAG_CHUNK_OVERLAP, RAG_CHUNK_SIZE
from document_rag.ingestion.file_formats import SUPPORTED_EXTENSIONS
from document_rag.ingestion.pdf_loader import PDFLoader
from document_rag.ingestion.wiki_loader import WikiLoader


def load_document(
    file_path: str | Path,
    chunk_size: int = RAG_CHUNK_SIZE,
    chunk_overlap: int = RAG_CHUNK_OVERLAP,
    scan_root: str | Path | None = None,
    *,
    pdf_loader: PDFLoader | None = None,
    wiki_loader: WikiLoader | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Dispatch a document to its format loader and return chunks with metadata."""
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported document format: {suffix or '(no extension)'}")

    if suffix == ".pdf":
        loader = pdf_loader or PDFLoader(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        result = loader.load_and_chunk(path, scan_root=scan_root)
    else:
        loader = wiki_loader or WikiLoader(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        method = {
            ".txt": loader.load_text_file,
            ".md": loader.load_markdown_file,
            ".docx": loader.load_docx_file,
        }[suffix]
        result = method(path, scan_root=scan_root)

    chunks = result.get("chunks") or []
    metadatas = result.get("metadatas") or []
    if len(chunks) != len(metadatas):
        raise ValueError(f"Document loader returned mismatched chunks and metadata for {path.name}.")
    return chunks, metadatas
