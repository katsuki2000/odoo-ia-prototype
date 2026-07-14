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

        # Initialize text splitter (token-based via tiktoken)
        self.splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
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

        with open(file_path, "r", encoding="utf-8") as f:
            source_code = f.read()

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

        with open(file_path, "r", encoding="utf-8") as f:
            xml_content = f.read()

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

    def load_js_file(
        self,
        file_path: str | Path,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Load and chunk a JavaScript file (Odoo OWL components).

        Args:
            file_path: Path to JS file
            metadata: Optional base metadata

        Returns:
            Dictionary with chunks, metadatas, and js_summary
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"JavaScript file not found: {file_path}")

        if file_path.suffix != ".js":
            raise ValueError(f"Expected .js file, got {file_path.suffix}")

        logger.info(f"Loading JavaScript file: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            source_code = f.read()

        # Initialize base metadata
        base_metadata = metadata or {}
        base_metadata.setdefault("source", str(file_path))
        base_metadata.setdefault("type", "code_js")
        base_metadata.setdefault("module", self._extract_module_name(file_path))

        # Extract JS structure info
        js_info = self._extract_js_info(source_code)

        # Use JS-aware separators for chunking
        js_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=[
                "\n\nexport ",   # ES module exports
                "\n\nclass ",    # Class declarations
                "\n\nfunction ", # Function declarations
                "\n\nconst ",    # Const declarations (often components)
                "\n\n",          # Paragraph
                "\n",            # Line
                " ",             # Word
                "",              # Character
            ],
        )

        chunks = js_splitter.split_text(source_code)
        logger.info(f"Created {len(chunks)} chunks from {file_path}")

        # Create metadata for each chunk
        metadatas = []
        for i, chunk in enumerate(chunks):
            chunk_metadata = base_metadata.copy()

            # Find which components/functions are in this chunk
            chunk_components = [
                c for c in js_info.get("components", []) if c in chunk
            ]
            chunk_functions = [
                f for f in js_info.get("functions", []) if f in chunk
            ]

            chunk_metadata.update(
                {
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "content_hash": self._compute_hash(chunk),
                    "components": chunk_components,
                    "functions": chunk_functions,
                    "is_owl_component": "Component" in chunk or "@odoo/owl" in chunk,
                }
            )
            metadatas.append(chunk_metadata)

        return {
            "chunks": chunks,
            "metadatas": metadatas,
            "js_summary": js_info,
        }

    def load_csv_file(
        self,
        file_path: str | Path,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Load and chunk a CSV file (e.g. Odoo ir.model.access.csv).

        Args:
            file_path: Path to CSV file
            metadata: Optional base metadata

        Returns:
            Dictionary with chunks, metadatas, and csv_summary
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"CSV file not found: {file_path}")

        logger.info(f"Loading CSV file: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Initialize base metadata
        base_metadata = metadata or {}
        base_metadata.setdefault("source", str(file_path))
        base_metadata.setdefault("type", "code_csv")
        base_metadata.setdefault("module", self._extract_module_name(file_path))

        # Use token-based splitter, splitting mostly by lines for CSV
        csv_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", " ", ""],
        )

        chunks = csv_splitter.split_text(content)
        logger.info(f"Created {len(chunks)} chunks from {file_path}")

        metadatas = []
        for i, chunk in enumerate(chunks):
            chunk_metadata = base_metadata.copy()
            chunk_metadata.update(
                {
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "content_hash": self._compute_hash(chunk),
                }
            )
            metadatas.append(chunk_metadata)

        return {
            "chunks": chunks,
            "metadatas": metadatas,
            "csv_summary": {"total_chunks": len(chunks)},
        }

    # Helper methods

    def _extract_js_info(self, source_code: str) -> dict[str, Any]:
        """Extract component and function names from JavaScript source."""
        info = {"components": [], "functions": [], "imports": []}

        # Extract class names (OWL components)
        for match in re.finditer(r"class\s+(\w+)\s+extends", source_code):
            info["components"].append(match.group(1))

        # Extract standalone function names
        for match in re.finditer(r"(?:export\s+)?function\s+(\w+)\s*\(", source_code):
            info["functions"].append(match.group(1))

        # Extract const arrow function components
        for match in re.finditer(r"(?:export\s+)?const\s+(\w+)\s*=\s*\(", source_code):
            info["functions"].append(match.group(1))

        # Extract imports
        for match in re.finditer(r"import\s+.*?from\s+[\"'](.+?)[\"']", source_code):
            info["imports"].append(match.group(1))

        return info

    def _extract_module_name(self, file_path: Path) -> str:
        """Extract module name from file path (e.g., 'account', 'sale')."""
        # Try to find a module folder in the path
        for part in file_path.parts:
            if part in ("account", "sale", "stock", "base", "hr"):
                return part

        return "unknown"

    def _extract_ast_info(self, source_code: str) -> dict[str, Any]:
        """Extract class and function information via AST parsing."""
        info = {"classes": [], "functions": [], "docstring": None}

        try:
            tree = ast.parse(source_code)
        except SyntaxError as e:
            logger.warning(f"Syntax error parsing Python file: {e}")
            return info

        # Extract module docstring
        if (
            tree.body
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
        ):
            info["docstring"] = tree.body[0].value.value

        # Extract classes and functions using a visitor
        class _ASTCollector(ast.NodeVisitor):
            def __init__(self):
                self.classes = []
                self.functions = []
                self.in_class = False

            def visit_ClassDef(self, node):
                class_info = {
                    "name": node.name,
                    "lineno": node.lineno,
                    "methods": [
                        n.name
                        for n in node.body
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    ],
                }
                self.classes.append(class_info)
                old_in_class = self.in_class
                self.in_class = True
                self.generic_visit(node)
                self.in_class = old_in_class

            def visit_FunctionDef(self, node):
                if not self.in_class:
                    func_info = {
                        "name": node.name,
                        "lineno": node.lineno,
                    }
                    self.functions.append(func_info)
                self.generic_visit(node)

            def visit_AsyncFunctionDef(self, node):
                if not self.in_class:
                    func_info = {
                        "name": node.name,
                        "lineno": node.lineno,
                    }
                    self.functions.append(func_info)
                self.generic_visit(node)

        collector = _ASTCollector()
        collector.visit(tree)
        info["classes"] = collector.classes
        info["functions"] = collector.functions

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


def load_js_directory(
    directory: str | Path,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
) -> list[dict[str, Any]]:
    """
    Load all JavaScript files from a directory.

    Args:
        directory: Path to directory containing .js files
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

    for js_file in directory.rglob("*.js"):
        # Skip node_modules and build directories
        if any(
            skip in js_file.parts
            for skip in ("node_modules", "dist", "build", ".git")
        ):
            continue

        try:
            logger.info(f"Processing {js_file.name}...")
            result = loader.load_js_file(js_file)
            documents.append(result)
        except Exception as e:
            logger.error(f"Error processing {js_file}: {e}")

    logger.info(f"Loaded {len(documents)} JavaScript files from {directory}")
    return documents

