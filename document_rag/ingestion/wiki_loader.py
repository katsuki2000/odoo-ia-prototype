"""Wiki and documentation loader for text, markdown, and Word files."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter

from config.settings import RAG_CHUNK_OVERLAP, RAG_CHUNK_SIZE
from document_rag.hashing import content_hash
from document_rag.ingestion.docx_reader import docx_to_markdown
from document_rag.ingestion.scan_root import compute_source

logger = logging.getLogger(__name__)

HEADING_RE = re.compile(r"^(#{1,6}) +(.+?) *$", re.MULTILINE)
TABLE_RULE_RE = re.compile(r"^\|(\s*:?-+:?\s*\|)+\s*$")
TABLE_ROW_RE = re.compile(r"^\|", re.MULTILINE)


def _chunk_starts(content: str, chunks: list[str]) -> list[int]:
    """Offset of each chunk in the content (-1 if not found); chunks come in order and may overlap."""
    starts, cursor = [], 0
    for chunk in chunks:
        start = content.find(chunk, cursor)
        starts.append(start)
        if start >= 0:
            cursor = start + 1
    return starts


def _heading_path(content: str, start: int) -> str:
    """Titles of the headings that govern the offset, outermost first, joined by ' > '."""
    stack: list[tuple[int, str]] = []
    for heading in HEADING_RE.finditer(content, 0, max(start, 0)):
        level = len(heading.group(1))
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, heading.group(2)))
    opening = HEADING_RE.match(content, start) if start > 0 else None
    while opening and stack and stack[-1][0] >= len(opening.group(1)):
        stack.pop()
    return " > ".join(title for _, title in stack)


def _table_header(content: str, start: int) -> str:
    """Header and rule rows of the table a chunk starts inside, so that its rows keep their column names."""
    if start <= 0 or content[start - 1] != "\n" or not content.startswith("|", start):
        return ""
    rows: list[str] = []
    for line in reversed(content[:start].split("\n")[:-1]):
        if not line.startswith("|"):
            break
        rows.append(line)
    if len(rows) >= 2 and TABLE_RULE_RE.match(rows[-2]):
        return f"{rows[-1]}\n{rows[-2]}"
    return ""


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

        starts = _chunk_starts(content, chunks) if is_markdown else []
        texts, metadatas = [], []
        for i, chunk in enumerate(chunks):
            chunk_metadata = base_metadata.copy()
            text = chunk
            if is_markdown:
                section = _heading_path(content, starts[i]) or None
                context = [f"[{section}]" if section else "", _table_header(content, starts[i]), chunk]
                text = "\n".join(filter(None, context))
            else:
                section = self._extract_section(chunk)
            chunk_metadata.update(
                {
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "content_hash": content_hash(text),
                    "section": section,
                    "has_code_block": "```" in chunk,
                }
            )
            if is_markdown:
                chunk_metadata["has_table"] = bool(TABLE_ROW_RE.search(chunk))
            texts.append(text)
            metadatas.append(chunk_metadata)

        return {"chunks": texts, "metadatas": metadatas}

    def _extract_section(self, text: str) -> Optional[str]:
        for line in text.split("\n"):
            line = line.strip()
            if line.isupper() and len(line) > 5:
                return line
        return None
