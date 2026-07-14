"""
Code document loader with AST/tree-sitter metadata extraction for
Python, XML, JavaScript, and CSV files.

Handles:
- Python files: stdlib `ast` parsing for class/function/docstring extraction
- XML files: tree-sitter structural parsing (Odoo <record>/<template> boundaries)
- JavaScript files: tree-sitter structural parsing (classes, functions, OWL components)
- CSV files: line-based token splitting (no structural parsing needed)

Chunks maintain structural metadata for semantic search optimization.
"""

from __future__ import annotations

import ast
import hashlib
import logging
from pathlib import Path
from typing import Any, Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter
from tree_sitter import Language, Node, Parser
import tree_sitter_javascript as tsjs
import tree_sitter_xml as tsxml

logger = logging.getLogger(__name__)

# Tree-sitter languages are loaded once at module level (parsing setup is
# not free, and Language objects are stateless / safe to share).
_XML_LANGUAGE = Language(tsxml.language_xml())
_JS_LANGUAGE = Language(tsjs.language())

# Odoo XML elements whose boundaries we chunk on. Anything else falls back
# to the token-based splitter.
_XML_RECORD_TAGS = {"record", "template"}

# JS node types that represent a top-level "unit" worth chunking on.
_JS_UNIT_NODE_TYPES = {
    "class_declaration",
    "function_declaration",
    "lexical_declaration",  # covers `const X = () => {...}` / `const X = class {...}`
}


class CodeLoader:
    """Loads and processes code files with AST/tree-sitter metadata extraction."""

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
    ):
        """
        Initialize code loader.

        Args:
            chunk_size: Number of tokens per chunk (token-based via tiktoken)
            chunk_overlap: Number of overlapping tokens between chunks
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        # Fallback splitter used for Python (primary) and for any structural
        # chunk (XML record, JS class/function) that exceeds chunk_size.
        self.splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\nclass ", "\ndef ", "\n    def ", "\n", " ", ""],
        )

        self._xml_parser = Parser(_XML_LANGUAGE)
        self._js_parser = Parser(_JS_LANGUAGE)

    # ------------------------------------------------------------------
    # Python (unchanged: stdlib ast, already solid)
    # ------------------------------------------------------------------

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

        base_metadata = metadata or {}
        base_metadata.setdefault("source", str(file_path))
        base_metadata.setdefault("type", "code_python")
        base_metadata.setdefault("module", self._extract_module_name(file_path))

        ast_info = self._extract_ast_info(source_code)

        chunks = self.splitter.split_text(source_code)
        logger.info(f"Created {len(chunks)} chunks from {file_path}")

        metadatas = []
        for i, chunk in enumerate(chunks):
            chunk_metadata = base_metadata.copy()

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

    # ------------------------------------------------------------------
    # XML (tree-sitter)
    # ------------------------------------------------------------------

    def load_xml_file(
        self,
        file_path: str | Path,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Load and chunk an XML file using tree-sitter structural parsing.

        Splits on <record> and <template> element boundaries (Odoo module
        patterns). Falls back to token-based splitting for any element that
        exceeds chunk_size, and for files with no matching elements at all.

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

        base_metadata = metadata or {}
        base_metadata.setdefault("source", str(file_path))
        base_metadata.setdefault("type", "code_xml")
        base_metadata.setdefault("module", self._extract_module_name(file_path))

        elements = self._split_xml_by_records(xml_content)

        chunks: list[str] = []
        chunk_extras: list[dict[str, Any]] = []

        if not elements:
            # No <record>/<template> found (e.g. a menu.xml with only
            # <menuitem> tags) — fall back to plain token splitting.
            for text in self.splitter.split_text(xml_content):
                chunks.append(text)
                chunk_extras.append({"tag": None, "record_id": None})
        else:
            for element in elements:
                text = element["text"]
                if self._estimate_tokens(text) > self.chunk_size:
                    # A single record/template is unusually large — split it
                    # further with the fallback splitter, but keep the tag
                    # metadata attached to every sub-chunk.
                    for sub_text in self.splitter.split_text(text):
                        chunks.append(sub_text)
                        chunk_extras.append(
                            {"tag": element["tag"], "record_id": element["record_id"]}
                        )
                else:
                    chunks.append(text)
                    chunk_extras.append(
                        {"tag": element["tag"], "record_id": element["record_id"]}
                    )

        logger.info(f"Created {len(chunks)} chunks from {file_path}")

        metadatas = []
        for i, (chunk, extra) in enumerate(zip(chunks, chunk_extras)):
            chunk_metadata = base_metadata.copy()
            chunk_metadata.update(
                {
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "content_hash": self._compute_hash(chunk),
                    "record_id": extra["record_id"] if extra["tag"] == "record" else None,
                    "template_id": extra["record_id"] if extra["tag"] == "template" else None,
                    "is_model_definition": "model=" in chunk,
                }
            )
            metadatas.append(chunk_metadata)

        return {
            "chunks": chunks,
            "metadatas": metadatas,
            "xml_summary": {"total_elements": len(elements), "total_chunks": len(chunks)},
        }

    def _split_xml_by_records(self, xml_content: str) -> list[dict[str, Any]]:
        """
        Split XML content by <record> and <template> element boundaries
        using a real tree-sitter parse tree (handles nesting, attributes
        with embedded '>', comments, and self-closing tags correctly,
        unlike a regex-based approach).

        Returns:
            List of {"text": str, "tag": str, "record_id": str | None}
        """
        source_bytes = xml_content.encode("utf-8")
        tree = self._xml_parser.parse(source_bytes)

        found: list[dict[str, Any]] = []

        def walk(node: Node) -> None:
            if node.type == "element":
                tag_name = self._xml_element_tag(node, source_bytes)
                if tag_name in _XML_RECORD_TAGS:
                    text = source_bytes[node.start_byte : node.end_byte].decode(
                        "utf-8", errors="replace"
                    )
                    found.append(
                        {
                            "text": text,
                            "tag": tag_name,
                            "record_id": self._xml_element_attr(node, source_bytes, "id"),
                        }
                    )
                    return  # don't descend into matched elements
            for child in node.children:
                walk(child)

        walk(tree.root_node)
        return found

    @staticmethod
    def _xml_element_tag(element_node: Node, source_bytes: bytes) -> Optional[str]:
        """Return the tag name of an XML `element` node (from its STag/EmptyElemTag)."""
        for child in element_node.children:
            if child.type in ("STag", "EmptyElemTag"):
                for grandchild in child.children:
                    if grandchild.type == "Name":
                        return source_bytes[
                            grandchild.start_byte : grandchild.end_byte
                        ].decode("utf-8", errors="replace")
        return None

    @staticmethod
    def _xml_element_attr(
        element_node: Node, source_bytes: bytes, attr_name: str
    ) -> Optional[str]:
        """Return the value of a given attribute on an XML element's start tag."""
        for child in element_node.children:
            if child.type in ("STag", "EmptyElemTag"):
                for attr_node in child.children:
                    if attr_node.type != "Attribute":
                        continue
                    name_text = None
                    value_text = None
                    for part in attr_node.children:
                        if part.type == "Name":
                            name_text = source_bytes[
                                part.start_byte : part.end_byte
                            ].decode("utf-8", errors="replace")
                        elif part.type == "AttValue":
                            value_text = source_bytes[
                                part.start_byte : part.end_byte
                            ].decode("utf-8", errors="replace").strip("\"'")
                    if name_text == attr_name:
                        return value_text
        return None

    # ------------------------------------------------------------------
    # JavaScript (tree-sitter)
    # ------------------------------------------------------------------

    def load_js_file(
        self,
        file_path: str | Path,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Load and chunk a JavaScript file using tree-sitter structural
        parsing (Odoo OWL components).

        Splits on top-level class declarations, function declarations, and
        `const X = ...` lexical declarations. Falls back to token-based
        splitting for oversized units and for files with no matching
        top-level structures.

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

        base_metadata = metadata or {}
        base_metadata.setdefault("source", str(file_path))
        base_metadata.setdefault("type", "code_js")
        base_metadata.setdefault("module", self._extract_module_name(file_path))

        units = self._split_js_by_units(source_code)

        chunks: list[str] = []
        chunk_extras: list[dict[str, Any]] = []

        if not units:
            for text in self.splitter.split_text(source_code):
                chunks.append(text)
                chunk_extras.append({"unit_type": None, "name": None})
        else:
            for unit in units:
                text = unit["text"]
                if self._estimate_tokens(text) > self.chunk_size:
                    for sub_text in self.splitter.split_text(text):
                        chunks.append(sub_text)
                        chunk_extras.append(
                            {"unit_type": unit["unit_type"], "name": unit["name"]}
                        )
                else:
                    chunks.append(text)
                    chunk_extras.append(
                        {"unit_type": unit["unit_type"], "name": unit["name"]}
                    )

        logger.info(f"Created {len(chunks)} chunks from {file_path}")

        all_components = [u["name"] for u in units if u["unit_type"] == "class" and u["name"]]
        all_functions = [
            u["name"] for u in units if u["unit_type"] in ("function", "lexical") and u["name"]
        ]

        metadatas = []
        for i, (chunk, extra) in enumerate(zip(chunks, chunk_extras)):
            chunk_metadata = base_metadata.copy()
            chunk_metadata.update(
                {
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "content_hash": self._compute_hash(chunk),
                    "components": [extra["name"]] if extra["unit_type"] == "class" and extra["name"] else [],
                    "functions": [extra["name"]] if extra["unit_type"] in ("function", "lexical") and extra["name"] else [],
                    "is_owl_component": "Component" in chunk or "@odoo/owl" in chunk,
                }
            )
            metadatas.append(chunk_metadata)

        return {
            "chunks": chunks,
            "metadatas": metadatas,
            "js_summary": {"components": all_components, "functions": all_functions},
        }

    def _split_js_by_units(self, source_code: str) -> list[dict[str, Any]]:
        """
        Split JS source into top-level structural units (classes, function
        declarations, const/let/var declarations) using tree-sitter, instead
        of regex keyword matching which false-positives on strings/comments.

        Returns:
            List of {"text": str, "unit_type": str, "name": str | None}
        """
        source_bytes = source_code.encode("utf-8")
        tree = self._js_parser.parse(source_bytes)

        units: list[dict[str, Any]] = []

        # Only walk top-level (program-level) nodes — we don't want to
        # recurse into every nested function, just the outer chunkable units.
        for node in tree.root_node.children:
            node_type = node.type
            if node_type == "export_statement":
                # unwrap `export class X` / `export function X` / `export const X`
                inner = node.child_by_field_name("declaration")
                if inner is not None:
                    node_type = inner.type
                    node = inner
                else:
                    continue

            if node_type not in _JS_UNIT_NODE_TYPES:
                continue

            text = source_bytes[node.start_byte : node.end_byte].decode(
                "utf-8", errors="replace"
            )
            name = self._js_unit_name(node, source_bytes)

            unit_type = {
                "class_declaration": "class",
                "function_declaration": "function",
                "lexical_declaration": "lexical",
            }[node_type]

            units.append({"text": text, "unit_type": unit_type, "name": name})

        return units

    @staticmethod
    def _js_unit_name(node: Node, source_bytes: bytes) -> Optional[str]:
        """Extract the name of a class/function/lexical declaration node."""
        if node.type in ("class_declaration", "function_declaration"):
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                return source_bytes[name_node.start_byte : name_node.end_byte].decode(
                    "utf-8", errors="replace"
                )
            return None

        if node.type == "lexical_declaration":
            # `const X = ...` — first declarator's identifier
            for child in node.children:
                if child.type == "variable_declarator":
                    name_node = child.child_by_field_name("name")
                    if name_node is not None:
                        return source_bytes[
                            name_node.start_byte : name_node.end_byte
                        ].decode("utf-8", errors="replace")
            return None

        return None

    # ------------------------------------------------------------------
    # CSV (unchanged)
    # ------------------------------------------------------------------

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

        base_metadata = metadata or {}
        base_metadata.setdefault("source", str(file_path))
        base_metadata.setdefault("type", "code_csv")
        base_metadata.setdefault("module", self._extract_module_name(file_path))

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

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _estimate_tokens(self, text: str) -> int:
        """
        Cheap token-count estimate used to decide whether a structural
        chunk (XML element / JS unit) needs further splitting.
        Uses the same tiktoken encoder as the fallback splitter for
        consistency, without paying for a full split.
        """
        try:
            return len(self.splitter._tokenizer.encode(text))
        except Exception:
            # Fallback heuristic if the tokenizer isn't accessible for any reason.
            return len(text) // 4

    def _extract_module_name(self, file_path: Path) -> str:
        """Extract module name from file path (e.g., 'account', 'sale')."""
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

        if (
            tree.body
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
        ):
            info["docstring"] = tree.body[0].value.value

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
                    self.functions.append({"name": node.name, "lineno": node.lineno})
                self.generic_visit(node)

            def visit_AsyncFunctionDef(self, node):
                if not self.in_class:
                    self.functions.append({"name": node.name, "lineno": node.lineno})
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
            if f"class {name}" in chunk or f"def {name}" in chunk:
                found.append(name)
        return found

    @staticmethod
    def _compute_hash(text: str) -> str:
        """Compute SHA-256 hash of text content."""
        return hashlib.sha256(text.encode()).hexdigest()[:12]


# ----------------------------------------------------------------------
# Directory-level convenience wrappers (unchanged behavior)
# ----------------------------------------------------------------------


def load_python_directory(
    directory: str | Path,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
) -> list[dict[str, Any]]:
    """Load all Python files from a directory."""
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError(f"Directory not found: {directory}")

    loader = CodeLoader(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    documents = []

    for py_file in directory.rglob("*.py"):
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
    """Load all XML files from a directory."""
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
    """Load all JavaScript files from a directory."""
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError(f"Directory not found: {directory}")

    loader = CodeLoader(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    documents = []

    for js_file in directory.rglob("*.js"):
        if any(skip in js_file.parts for skip in ("node_modules", "dist", "build", ".git")):
            continue
        try:
            logger.info(f"Processing {js_file.name}...")
            result = loader.load_js_file(js_file)
            documents.append(result)
        except Exception as e:
            logger.error(f"Error processing {js_file}: {e}")

    logger.info(f"Loaded {len(documents)} JavaScript files from {directory}")
    return documents