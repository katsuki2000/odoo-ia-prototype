"""Wiki and documentation loader for text, markdown, and Word files."""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter

from config.settings import RAG_CHUNK_OVERLAP, RAG_CHUNK_SIZE
from document_rag.ingestion.docx_reader import docx_to_markdown
from document_rag.ingestion.file_formats import is_supported_document
from document_rag.ingestion.scan_root import compute_source

logger = logging.getLogger(__name__)


class WikiLoader:
    """Loads and processes wiki and documentation files."""

    def __init__(
        self,
        chunk_size: int = RAG_CHUNK_SIZE,
        chunk_overlap: int = RAG_CHUNK_OVERLAP,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n## ", "\n# ", "\n\n", "\n", " ", ""],
        )

    def load_text_file(
        self,
        file_path: str | Path,
        metadata: Optional[dict[str, Any]] = None,
        scan_root: Optional[str | Path] = None,
    ) -> dict[str, Any]:
        path = self._validate_file(file_path, (".txt",))
        logger.info("Loading text file: %s", path)
        content = path.read_text(encoding="utf-8")
        return self._chunk_content(content, path, metadata, scan_root, is_markdown=False)

    def load_markdown_file(
        self,
        file_path: str | Path,
        metadata: Optional[dict[str, Any]] = None,
        scan_root: Optional[str | Path] = None,
    ) -> dict[str, Any]:
        path = self._validate_file(file_path, (".md",))
        logger.info("Loading markdown file: %s", path)
        content = path.read_text(encoding="utf-8")
        return self._chunk_markdown(content, path, metadata, scan_root)

    def load_docx_file(
        self,
        file_path: str | Path,
        metadata: Optional[dict[str, Any]] = None,
        scan_root: Optional[str | Path] = None,
    ) -> dict[str, Any]:
        path = self._validate_file(file_path, (".docx",))
        logger.info("Loading Word file: %s", path)
        return self._chunk_markdown(docx_to_markdown(path), path, metadata, scan_root)

    def _validate_file(self, file_path: str | Path, allowed_suffixes: tuple[str, ...]) -> Path:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if path.suffix.lower() not in allowed_suffixes:
            raise ValueError(f"Expected {allowed_suffixes} file, got {path.suffix}")
        return path

    def _chunk_markdown(
        self,
        content: str,
        file_path: Path,
        metadata: Optional[dict[str, Any]],
        scan_root: Optional[str | Path],
    ) -> dict[str, Any]:
        return self._chunk_content(content, file_path, metadata, scan_root, is_markdown=True)

    def _chunk_content(
        self,
        content: str,
        file_path: Path,
        metadata: Optional[dict[str, Any]],
        scan_root: Optional[str | Path],
        is_markdown: bool,
    ) -> dict[str, Any]:
        base_metadata = metadata or {}
        base_metadata.setdefault("source", compute_source(file_path, scan_root))
        base_metadata.setdefault("type", "doc_wiki")

        if is_markdown:
            h1_match = re.search(r"^# (.+)$", content, re.MULTILINE)
            title = h1_match.group(1).strip() if h1_match else file_path.stem
        else:
            lines = content.strip().split("\n")
            title = lines[0].strip() if lines else file_path.stem
        base_metadata["title"] = title

        chunks = self.splitter.split_text(content)
        logger.info("Created %d chunks from %s", len(chunks), file_path)

        metadatas = []
        for i, chunk in enumerate(chunks):
            chunk_metadata = base_metadata.copy()
            section = self._extract_markdown_section(chunk) if is_markdown else self._extract_section(chunk)
            chunk_metadata.update(
                {
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "content_hash": self._compute_hash(chunk),
                    "section": section,
                    "has_code_block": "```" in chunk,
                }
            )
            if is_markdown:
                chunk_metadata["has_table"] = "|" in chunk and "-" in chunk
            metadatas.append(chunk_metadata)

        return {"chunks": chunks, "metadatas": metadatas}

    def _extract_section(self, text: str) -> Optional[str]:
        for line in text.split("\n"):
            line = line.strip()
            if line.isupper() and len(line) > 5:
                return line
        return None

    def _extract_markdown_section(self, text: str) -> Optional[str]:
        h2_match = re.search(r"^## (.+)$", text, re.MULTILINE)
        if h2_match:
            return h2_match.group(1).strip()
        h3_match = re.search(r"^### (.+)$", text, re.MULTILINE)
        if h3_match:
            return h3_match.group(1).strip()
        return None

    @staticmethod
    def _compute_hash(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:12]


def load_wiki_directory(
    directory: str | Path,
    chunk_size: int = RAG_CHUNK_SIZE,
    chunk_overlap: int = RAG_CHUNK_OVERLAP,
    scan_root: Optional[str | Path] = None,
) -> list[dict[str, Any]]:
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError(f"Directory not found: {directory}")

    root = Path(scan_root) if scan_root is not None else directory
    loader = WikiLoader(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    documents = []

    load_methods = {
        ".txt": loader.load_text_file,
        ".md": loader.load_markdown_file,
        ".docx": loader.load_docx_file,
    }
    for path in sorted(directory.iterdir()):
        method = load_methods.get(path.suffix.lower())
        if not path.is_file() or method is None or not is_supported_document(path):
            continue
        try:
            documents.append(method(path, scan_root=root))
        except Exception:
            logger.exception("Failed to process document: %s", path.name)

    logger.info("Loaded %d text-based documents from %s", len(documents), directory)
    return documents
