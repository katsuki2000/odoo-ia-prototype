"""
Wiki and documentation loader for text and markdown files.

Handles:
- Plain text files (.txt)
- Markdown files (.md)

Simple chunking with metadata extraction.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter

from document_rag.ingestion.scan_root import compute_source

logger = logging.getLogger(__name__)


class WikiLoader:
    """Loads and processes wiki and documentation files."""

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
    ):
        """
        Initialize wiki loader.

        Args:
            chunk_size: Number of characters per chunk
            chunk_overlap: Number of overlapping characters between chunks
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        # Initialize text splitter with wiki-friendly separators (token-based via tiktoken)
        self.splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=[
                "\n## ",  # Markdown h2
                "\n# ",   # Markdown h1
                "\n\n",   # Paragraph
                "\n",     # Line
                " ",      # Word
                "",       # Character
            ],
        )

    def load_text_file(
        self,
        file_path: str | Path,
        metadata: Optional[dict[str, Any]] = None,
        scan_root: Optional[str | Path] = None,
    ) -> dict[str, Any]:
        """
        Load and chunk a plain text file.

        Args:
            file_path: Path to .txt file
            metadata: Optional base metadata
            scan_root: Logical root `source` is made relative to (see
                document_rag/ingestion/scan_root.py). Falls back to the
                absolute path when omitted.

        Returns:
            Dictionary with chunks and metadatas
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Text file not found: {file_path}")

        if file_path.suffix != ".txt":
            raise ValueError(f"Expected .txt file, got {file_path.suffix}")

        logger.info(f"Loading text file: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Initialize base metadata
        base_metadata = metadata or {}
        base_metadata.setdefault("source", compute_source(file_path, scan_root))
        base_metadata.setdefault("type", "doc_wiki")

        # Extract title (first non-empty line)
        lines = content.strip().split("\n")
        title = lines[0].strip() if lines else file_path.stem
        base_metadata["title"] = title

        # Chunk the content
        chunks = self.splitter.split_text(content)
        logger.info(f"Created {len(chunks)} chunks from {file_path}")

        # Create metadata for each chunk
        metadatas = []
        for i, chunk in enumerate(chunks):
            chunk_metadata = base_metadata.copy()

            # Extract section if available
            section = self._extract_section(chunk)

            chunk_metadata.update(
                {
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "content_hash": self._compute_hash(chunk),
                    "section": section,
                    "has_code_block": "```" in chunk,
                }
            )
            metadatas.append(chunk_metadata)

        return {
            "chunks": chunks,
            "metadatas": metadatas,
        }

    def load_markdown_file(
        self,
        file_path: str | Path,
        metadata: Optional[dict[str, Any]] = None,
        scan_root: Optional[str | Path] = None,
    ) -> dict[str, Any]:
        """
        Load and chunk a markdown file.

        Args:
            file_path: Path to .md file
            metadata: Optional base metadata
            scan_root: Logical root `source` is made relative to (see
                document_rag/ingestion/scan_root.py). Falls back to the
                absolute path when omitted.

        Returns:
            Dictionary with chunks and metadatas
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Markdown file not found: {file_path}")

        if file_path.suffix != ".md":
            raise ValueError(f"Expected .md file, got {file_path.suffix}")

        logger.info(f"Loading markdown file: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Initialize base metadata
        base_metadata = metadata or {}
        base_metadata.setdefault("source", compute_source(file_path, scan_root))
        base_metadata.setdefault("type", "doc_wiki")

        # Extract title (first h1 or filename)
        h1_match = re.search(r"^# (.+)$", content, re.MULTILINE)
        if h1_match:
            title = h1_match.group(1).strip()
        else:
            title = file_path.stem

        base_metadata["title"] = title

        # Chunk the content
        chunks = self.splitter.split_text(content)
        logger.info(f"Created {len(chunks)} chunks from {file_path}")

        # Create metadata for each chunk
        metadatas = []
        for i, chunk in enumerate(chunks):
            chunk_metadata = base_metadata.copy()

            # Extract section heading
            section = self._extract_markdown_section(chunk)

            chunk_metadata.update(
                {
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "content_hash": self._compute_hash(chunk),
                    "section": section,
                    "has_code_block": "```" in chunk,
                    "has_table": "|" in chunk and "-" in chunk,
                }
            )
            metadatas.append(chunk_metadata)

        return {
            "chunks": chunks,
            "metadatas": metadatas,
        }

    # Helper methods

    def _extract_section(self, text: str) -> Optional[str]:
        """Extract section name from text (simple heuristic)."""
        lines = text.split("\n")
        for line in lines:
            line = line.strip()
            # Look for all-caps lines that might be section headers
            if line.isupper() and len(line) > 5:
                return line
        return None

    def _extract_markdown_section(self, text: str) -> Optional[str]:
        """Extract markdown section heading from text."""
        # Look for markdown headings
        h2_match = re.search(r"^## (.+)$", text, re.MULTILINE)
        if h2_match:
            return h2_match.group(1).strip()

        h3_match = re.search(r"^### (.+)$", text, re.MULTILINE)
        if h3_match:
            return h3_match.group(1).strip()

        return None

    @staticmethod
    def _compute_hash(text: str) -> str:
        """Compute SHA-256 hash of text content."""
        return hashlib.sha256(text.encode()).hexdigest()[:12]


def load_wiki_directory(
    directory: str | Path,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
    scan_root: Optional[str | Path] = None,
) -> list[dict[str, Any]]:
    """
    Load all text and markdown files from a directory.

    Args:
        directory: Path to directory containing .txt and .md files
        chunk_size: Chunk size for splitting
        chunk_overlap: Chunk overlap for splitting
        scan_root: Logical root `source` is made relative to. Defaults to
            `directory` itself when omitted.

    Returns:
        List of document dictionaries with chunks and metadatas
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError(f"Directory not found: {directory}")

    root = Path(scan_root) if scan_root is not None else directory
    loader = WikiLoader(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    documents = []

    # Load text files
    for txt_file in directory.glob("*.txt"):
        try:
            logger.info(f"Processing {txt_file.name}...")
            result = loader.load_text_file(txt_file, scan_root=root)
            documents.append(result)
        except Exception as e:
            logger.error(f"Error processing {txt_file}: {e}")

    # Load markdown files
    for md_file in directory.glob("*.md"):
        try:
            logger.info(f"Processing {md_file.name}...")
            result = loader.load_markdown_file(md_file, scan_root=root)
            documents.append(result)
        except Exception as e:
            logger.error(f"Error processing {md_file}: {e}")

    logger.info(f"Loaded {len(documents)} wiki files from {directory}")
    return documents
