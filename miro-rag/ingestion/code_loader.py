"""
Code document loader with AST metadata extraction for Python and XML files.

Handles:
- Python files: AST parsing for class/function/docstring extraction
- XML files: Template and record boundary detection (Odoo module patterns)

Chunks maintain AST metadata for semantic search optimization.
"""

from __future__ import annotations

import ast
import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)


class CodeLoader:
    """Loads and processes code files with AST metadata extraction."""

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
    ):
        """
        Initialize code loader.

        Args:
            chunk_size: Number of characters per chunk
            chunk_overlap: Number of overlapping characters between chunks
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        # Initialize text splitter
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\nclass ", "\ndef ", "\n    def ", "\n", " ", ""],
        )

    def load_python_file(
        self,
        file_path: str | Path,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Load and chunk a Python file with AST metadata.

        Args:
            file_path: Path to Python file
            metadata: Optional base metadata

        Returns:
            Dictionary with chunks, metadatas, and ast_summary
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Python file not found: {file_path}")

        if file_path.suffix != ".py":
            raise ValueError(f"Expected .py file, got {file_path.suffix}")

        logger.info(f"Loading Python file: {file_path}")

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            source_code = f.read().replace("\x00", "")

        # Initialize base metadata
        base_metadata = metadata or {}
        base_metadata.setdefault("source", str(file_path))
        base_metadata.setdefault("type", "code_python")
        base_metadata.setdefault("module", self._extract_module_name(file_path))

        # Extract AST information
        ast_info = self._extract_ast_info(source_code)

        # Chunk the code
        chunks = self.splitter.split_text(source_code)
        logger.info(f"Created {len(chunks)} chunks from {file_path}")

        # Create metadata for each chunk
        metadatas = []
        for i, chunk in enumerate(chunks):
            chunk_metadata = base_metadata.copy()

            # Find which classes and functions are in this chunk
            chunk_classes = self._find_ast_elements_in_chunk(
                chunk, ast_info.get("classes", [])
            )
            chunk_functions = self._find_ast_elements_in_chunk(
                chunk, ast_info.get("functions", [])
            )

            chunk_metadata.update(
                {
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "content_hash": self._compute_hash(chunk),
                    "classes": chunk_classes,
                    "functions": chunk_functions,
                    "has_docstring": "\"\"\"" in chunk or "'''" in chunk,
                }
            )
            metadatas.append(chunk_metadata)

        return {
            "chunks": chunks,
            "metadatas": metadatas,
            "ast_summary": ast_info,
        }

    def load_xml_file(
        self,
        file_path: str | Path,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Load and chunk an XML file (Odoo template/record patterns).

        Splits on <record> and <template> boundaries.

        Args:
            file_path: Path to XML file
            metadata: Optional base metadata

        Returns:
            Dictionary with chunks, metadatas, and xml_summary
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"XML file not found: {file_path}")

        if file_path.suffix != ".xml":
            raise ValueError(f"Expected .xml file, got {file_path.suffix}")

        logger.info(f"Loading XML file: {file_path}")

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            xml_content = f.read().replace("\x00", "")

        # Initialize base metadata
        base_metadata = metadata or {}
        base_metadata.setdefault("source", str(file_path))
        base_metadata.setdefault("type", "code_xml")
        base_metadata.setdefault("module", self._extract_module_name(file_path))

        # Split by record and template boundaries
        chunks = self._split_xml_by_records(xml_content)

        if not chunks:
            chunks = self.splitter.split_text(xml_content)

        logger.info(f"Created {len(chunks)} chunks from {file_path}")

        # Create metadata for each chunk
        metadatas = []
        for i, chunk in enumerate(chunks):
            chunk_metadata = base_metadata.copy()

            # Extract record/template info
            record_id = self._extract_xml_id(chunk, "record")
            template_id = self._extract_xml_id(chunk, "template")

            chunk_metadata.update(
                {
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "content_hash": self._compute_hash(chunk),
                    "record_id": record_id,
                    "template_id": template_id,
                    "is_model_definition": "model=" in chunk,
                }
            )
            metadatas.append(chunk_metadata)

        return {
            "chunks": chunks,
            "metadatas": metadatas,
            "xml_summary": {"total_records": len(chunks)},
        }

    # Helper methods

    def _extract_module_name(self, file_path: Path) -> str:
        """Extract module name from file path (e.g., 'account', 'sale')."""
        # Try to find a module folder in the path
        for part in file_path.parts:
            if part in ("account", "sale", "stock", "base", "hr"):
                return part

        return "unknown"

    def _extract_ast_info(self, source_code: str) -> dict[str, Any]:
        """Extract class and function information via AST parsing using tree-sitter."""
        info = {"classes": [], "functions": [], "docstring": None}

        try:
            import tree_sitter_python as tspython
            from tree_sitter import Language, Parser
            
            PY_LANGUAGE = Language(tspython.language())
            parser = Parser()
            parser.language = PY_LANGUAGE
            tree = parser.parse(bytes(source_code, "utf8"))
            
            def traverse(node, in_class=False):
                if node.type == 'class_definition':
                    class_name = None
                    for child in node.children:
                        if child.type == 'identifier':
                            class_name = child.text.decode("utf8")
                            info["classes"].append({"name": class_name, "lineno": node.start_point[0] + 1})
                            break
                    for child in node.children:
                        traverse(child, in_class=True)
                elif node.type == 'function_definition':
                    if not in_class:
                        for child in node.children:
                            if child.type == 'identifier':
                                info["functions"].append({"name": child.text.decode("utf8"), "lineno": node.start_point[0] + 1})
                                break
                    for child in node.children:
                        traverse(child, in_class=in_class)
                else:
                    # Check for module docstring
                    if node.type == 'module' and len(node.children) > 0 and node.children[0].type == 'expression_statement':
                        expr = node.children[0]
                        if len(expr.children) > 0 and expr.children[0].type == 'string':
                            info["docstring"] = expr.children[0].text.decode("utf8").strip('\'"')
                    
                    for child in node.children:
                        traverse(child, in_class=in_class)

            traverse(tree.root_node)
            
        except Exception as e:
            logger.warning(f"Tree-sitter error parsing Python file: {e}")

        return info

    def _find_ast_elements_in_chunk(
        self, chunk: str, elements: list[dict[str, Any]]
    ) -> list[str]:
        """Find which AST elements (classes/functions) are mentioned in a chunk."""
        found = []
        for element in elements:
            name = element.get("name", "")
            # Simple text search - not perfect but fast
            if f"class {name}" in chunk or f"def {name}" in chunk:
                found.append(name)

        return found

    def _split_xml_by_records(self, xml_content: str) -> list[str]:
        """Split XML content by <record> and <template> boundaries."""
        chunks = []

        # Find all record and template blocks
        pattern = r"(<record[^>]*>.*?</record>|<template[^>]*>.*?</template>)"
        matches = re.finditer(pattern, xml_content, re.DOTALL)

        for match in matches:
            chunk = match.group(0)
            if chunk.strip():
                chunks.append(chunk)

        return chunks

    def _extract_xml_id(self, xml_chunk: str, tag: str) -> Optional[str]:
        """Extract id attribute from XML tag."""
        pattern = rf'<{tag}[^>]*id=["\']([^"\']+)["\']'
        match = re.search(pattern, xml_chunk)
        return match.group(1) if match else None

    @staticmethod
    def _compute_hash(text: str) -> str:
        """Compute SHA-256 hash of text content."""
        return hashlib.sha256(text.encode()).hexdigest()[:12]


def load_python_directory(
    directory: str | Path,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
) -> list[dict[str, Any]]:
    """
    Load all Python files from a directory.

    Args:
        directory: Path to directory containing .py files
        chunk_size: Chunk size for splitting
        chunk_overlap: Chunk overlap for splitting

    Returns:
        List of document dictionaries with chunks and metadatas
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError(f"Directory not found: {directory}")

    loader = CodeLoader(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    documents = []

    for py_file in directory.rglob("*.py"):
        # Skip __pycache__ and venv directories
        if "__pycache__" in py_file.parts or "venv" in py_file.parts:
            continue

        try:
            logger.info(f"Processing {py_file.name}...")
            result = loader.load_python_file(py_file)
            documents.append(result)
        except Exception as e:
            logger.error(f"Error processing {py_file}: {e}")

    logger.info(f"Loaded {len(documents)} Python files from {directory}")
    return documents


def load_xml_directory(
    directory: str | Path,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
) -> list[dict[str, Any]]:
    """
    Load all XML files from a directory.

    Args:
        directory: Path to directory containing .xml files
        chunk_size: Chunk size for splitting
        chunk_overlap: Chunk overlap for splitting

    Returns:
        List of document dictionaries with chunks and metadatas
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError(f"Directory not found: {directory}")

    loader = CodeLoader(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    documents = []

    for xml_file in directory.rglob("*.xml"):
        try:
            logger.info(f"Processing {xml_file.name}...")
            result = loader.load_xml_file(xml_file)
            documents.append(result)
        except Exception as e:
            logger.error(f"Error processing {xml_file}: {e}")

    logger.info(f"Loaded {len(documents)} XML files from {directory}")
    return documents
