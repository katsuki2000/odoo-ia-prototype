"""
Incremental ingestion utilities.

Re-indexes only files whose chunk content hashes changed, adds new files, and
removes ChromaDB chunks for files deleted from the scanned roots.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import logging
from pathlib import Path
from typing import Any, Iterable

from document_rag.ingestion.code_loader import CodeLoader
from document_rag.ingestion.logging_utils import start_timer, write_ingestion_event
from document_rag.ingestion.pdf_loader import PDFLoader
from document_rag.ingestion.wiki_loader import WikiLoader
from document_rag.vectorstore.chroma_manager import ChromaManager

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".py", ".xml", ".js", ".csv"}
SKIP_PARTS = {"__pycache__", "venv", ".venv", ".git", "site-packages", ".pytest_cache"}


@dataclass
class IncrementalResult:
    """Summary of an incremental indexing run."""

    added_files: list[str] = field(default_factory=list)
    updated_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    failed_files: dict[str, str] = field(default_factory=dict)
    chunks_added: int = 0
    chunks_deleted: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict for logging and API responses."""
        return asdict(self)


def reindex_if_changed(
    roots: Iterable[str | Path],
    docs_manager: ChromaManager | None = None,
    code_manager: ChromaManager | None = None,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
) -> dict[str, Any]:
    """
    Incrementally synchronize supported files under roots with ChromaDB.

    Args:
        roots: Directories or individual files to scan.
        docs_manager: Manager for doc collections.
        code_manager: Manager for code collections.
        chunk_size: Loader chunk size.
        chunk_overlap: Loader chunk overlap.

    Returns:
        Dict summary containing added, updated, deleted, skipped, and failed files.
    """
    started_at = start_timer()
    docs_manager = docs_manager or ChromaManager(collection_name="odoo_docs")
    code_manager = code_manager or ChromaManager(collection_name="odoo_code")
    result = IncrementalResult()

    root_paths = [Path(root).resolve() for root in roots if str(root)]
    current_files = _scan_supported_files(root_paths)
    current_sources = {str(file_path) for file_path in current_files}
    existing_sources_docs = _get_existing_sources(docs_manager)
    existing_sources_code = _get_existing_sources(code_manager)
    
    # Track deleted sources for each manager
    for manager, existing_sources in [(docs_manager, existing_sources_docs), (code_manager, existing_sources_code)]:
        for source in sorted(existing_sources):
            if not _is_under_roots(source, root_paths):
                continue
            if source in current_sources:
                continue
    
            try:
                deleted_count = manager.delete_by_source(source)
                logger.info("Deleted removed source: %s (%d chunks)", source, deleted_count)
                result.deleted_files.append(source)
                result.chunks_deleted += deleted_count
            except Exception as exc:
                logger.error("Failed deleting removed source %s: %s", source, exc)
                result.failed_files[source] = str(exc)

    for file_path in current_files:
        source = str(file_path)
        manager = docs_manager if file_path.suffix.lower() in {".pdf", ".txt", ".md"} else code_manager
        try:
            chunks, metadatas = _load_file(file_path, chunk_size, chunk_overlap)
            if not chunks:
                result.skipped_files.append(source)
                continue

            new_hashes = _metadata_hashes(metadatas)
            old_hashes = _get_hashes_for_source(manager, source)

            if old_hashes == new_hashes:
                logger.info("Skipping unchanged source: %s", source)
                result.skipped_files.append(source)
                continue

            deleted_count = manager.delete_by_source(source) if old_hashes else 0
            ids = manager.add_chunks(chunks, metadatas)

            if old_hashes:
                result.updated_files.append(source)
                logger.info(
                    "Updated changed source: %s (%d added, %d deleted)",
                    source,
                    len(ids),
                    deleted_count,
                )
            else:
                result.added_files.append(source)
                logger.info("Added new source: %s (%d chunks)", source, len(ids))

            result.chunks_deleted += deleted_count
            result.chunks_added += len(ids)
        except Exception as exc:
            logger.error("Failed incremental indexing for %s: %s", source, exc)
            result.failed_files[source] = str(exc)

    result_dict = result.to_dict()
    write_ingestion_event(
        event_type="incremental_reindex",
        result=result_dict,
        started_at=started_at,
    )
    return result_dict


def _scan_supported_files(roots: list[Path]) -> list[Path]:
    """Return all supported files under the supplied roots."""
    files: list[Path] = []

    for root in roots:
        if root.is_file():
            if _is_supported_file(root):
                files.append(root)
            else:
                logger.info("Skipping unsupported file: %s", root)
        elif root.is_dir():
            for file_path in root.rglob("*"):
                if _is_supported_file(file_path):
                    files.append(file_path.resolve())
        else:
            logger.warning("Incremental root does not exist: %s", root)

    return sorted(set(files))


def _is_supported_file(file_path: Path) -> bool:
    """Return True if the path is a supported source file."""
    if not file_path.is_file():
        return False

    if any(part.lower() in SKIP_PARTS for part in file_path.parts):
        return False

    return file_path.suffix.lower() in SUPPORTED_EXTENSIONS


def _load_file(
    file_path: Path,
    chunk_size: int,
    chunk_overlap: int,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Load one supported file and return chunks plus metadata."""
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        loaded = PDFLoader(chunk_size=chunk_size, chunk_overlap=chunk_overlap).load_and_chunk(file_path)
    elif suffix == ".txt":
        loaded = WikiLoader(chunk_size=chunk_size, chunk_overlap=chunk_overlap).load_text_file(file_path)
    elif suffix == ".md":
        loaded = WikiLoader(chunk_size=chunk_size, chunk_overlap=chunk_overlap).load_markdown_file(file_path)
    elif suffix == ".py":
        loaded = CodeLoader(chunk_size=chunk_size, chunk_overlap=chunk_overlap).load_python_file(file_path)
    elif suffix == ".xml":
        loaded = CodeLoader(chunk_size=chunk_size, chunk_overlap=chunk_overlap).load_xml_file(file_path)
    elif suffix == ".js":
        loaded = CodeLoader(chunk_size=chunk_size, chunk_overlap=chunk_overlap).load_js_file(file_path)
    elif suffix == ".csv":
        loaded = CodeLoader(chunk_size=chunk_size, chunk_overlap=chunk_overlap).load_csv_file(file_path)
    else:
        raise ValueError(f"Unsupported file type: {file_path.suffix}")

    chunks = loaded.get("chunks", [])
    metadatas = loaded.get("metadatas", [])
    return chunks, metadatas


def _get_existing_sources(manager: ChromaManager) -> set[str]:
    """Return unique source values currently stored in ChromaDB."""
    try:
        existing = manager.collection.get(include=["metadatas"])
    except Exception as exc:
        logger.error("Failed reading ChromaDB inventory: %s", exc)
        return set()

    sources = set()
    for metadata in existing.get("metadatas", []):
        source = metadata.get("source") if metadata else None
        if source:
            sources.add(str(source))

    return sources


def _get_hashes_for_source(manager: ChromaManager, source: str) -> list[str]:
    """Return ordered content hashes for all chunks of a source."""
    try:
        existing = manager.collection.get(
            where={"source": {"$eq": source}},
            include=["metadatas"],
        )
    except Exception as exc:
        logger.error("Failed reading source hashes for %s: %s", source, exc)
        return []

    metadatas = existing.get("metadatas", [])
    return _metadata_hashes(metadatas)


def _metadata_hashes(metadatas: list[dict[str, Any]]) -> list[str]:
    """Return content hashes sorted by chunk index for stable comparison."""
    def _sort_key(metadata: dict[str, Any]) -> tuple[int, str]:
        chunk_index = metadata.get("chunk_index", 0)
        content_hash = str(metadata.get("content_hash", ""))
        return int(chunk_index), content_hash

    hashes = []
    for metadata in sorted(metadatas, key=_sort_key):
        content_hash = metadata.get("content_hash")
        if content_hash:
            hashes.append(str(content_hash))

    return hashes


def _is_under_roots(source: str, roots: list[Path]) -> bool:
    """Return True if an indexed source belongs to the scanned roots."""
    try:
        source_path = Path(source).resolve()
    except Exception:
        return False

    for root in roots:
        try:
            if root.is_file() and source_path == root:
                return True
            if root.is_dir() and source_path.is_relative_to(root):
                return True
        except Exception:
            continue

    return False
