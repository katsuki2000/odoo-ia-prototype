"""
document_rag/ingestion/code_loader.py

Code document loader with AST/tree-sitter metadata extraction for
Python, XML, JavaScript, and CSV files.

Facade and unified CodeLoader class delegating to format-specific submodules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter
from tree_sitter import Node, Parser

from document_rag.ingestion.code_loader_common import (
    compute_hash,
    estimate_tokens,
    extract_module_name,
)
from document_rag.ingestion.code_loader_js_csv import (
    _JS_LANGUAGE,
    _JS_UNIT_NODE_TYPES,
    js_unit_name,
    load_csv_file_impl,
    load_js_directory,
    load_js_file_impl,
    split_js_by_units,
)
from document_rag.ingestion.code_loader_python import (
    build_python_file_header,
    extract_ast_info,
    find_ast_elements_in_chunk,
    load_python_directory,
    load_python_file_impl,
)
from document_rag.ingestion.code_loader_xml import (
    _XML_LANGUAGE,
    _XML_RECORD_TAGS,
    load_xml_directory,
    load_xml_file_impl,
    split_xml_by_records,
    xml_element_attr,
    xml_element_tag,
)


class CodeLoader:
    """Loads and processes code files with AST/tree-sitter metadata extraction."""

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
    ):
        """Initialize code loader with token splitter and tree-sitter parsers."""
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        self.splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\nclass ", "\ndef ", "\n    def ", "\n", " ", ""],
        )

        self._xml_parser = Parser(_XML_LANGUAGE)
        self._js_parser = Parser(_JS_LANGUAGE)

    def load_python_file(
        self,
        file_path: str | Path,
        metadata: Optional[dict[str, Any]] = None,
        scan_root: Optional[str | Path] = None,
    ) -> dict[str, Any]:
        """Load and chunk a Python file with AST metadata."""
        return load_python_file_impl(
            splitter=self.splitter,
            file_path=file_path,
            metadata=metadata,
            scan_root=scan_root,
        )

    def load_xml_file(
        self,
        file_path: str | Path,
        metadata: Optional[dict[str, Any]] = None,
        scan_root: Optional[str | Path] = None,
    ) -> dict[str, Any]:
        """Load and chunk an XML file using tree-sitter structural parsing."""
        return load_xml_file_impl(
            xml_parser=self._xml_parser,
            splitter=self.splitter,
            chunk_size=self.chunk_size,
            file_path=file_path,
            metadata=metadata,
            scan_root=scan_root,
        )

    def load_js_file(
        self,
        file_path: str | Path,
        metadata: Optional[dict[str, Any]] = None,
        scan_root: Optional[str | Path] = None,
    ) -> dict[str, Any]:
        """Load and chunk a JavaScript file using tree-sitter structural parsing."""
        return load_js_file_impl(
            js_parser=self._js_parser,
            splitter=self.splitter,
            chunk_size=self.chunk_size,
            file_path=file_path,
            metadata=metadata,
            scan_root=scan_root,
        )

    def load_csv_file(
        self,
        file_path: str | Path,
        metadata: Optional[dict[str, Any]] = None,
        scan_root: Optional[str | Path] = None,
    ) -> dict[str, Any]:
        """Load and chunk a CSV file (e.g. Odoo ir.model.access.csv)."""
        return load_csv_file_impl(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            file_path=file_path,
            metadata=metadata,
            scan_root=scan_root,
        )

    # ------------------------------------------------------------------
    # Helper delegations for backward compatibility
    # ------------------------------------------------------------------

    def _estimate_tokens(self, text: str) -> int:
        return estimate_tokens(self.splitter, text)

    def _extract_module_name(
        self, file_path: Path, scan_root: Optional[Path] = None
    ) -> str:
        return extract_module_name(file_path, scan_root)

    def _extract_ast_info(self, source_code: str) -> dict[str, Any]:
        return extract_ast_info(source_code)

    def _find_ast_elements_in_chunk(
        self, chunk: str, elements: list[dict[str, Any]]
    ) -> list[str]:
        return find_ast_elements_in_chunk(chunk, elements)

    def _build_python_file_header(
        self,
        file_path: Path,
        ast_info: dict[str, Any],
        scan_root: Optional[Path] = None,
    ) -> str:
        return build_python_file_header(file_path, ast_info, scan_root=scan_root)

    def _split_xml_by_records(self, xml_content: str) -> list[dict[str, Any]]:
        return split_xml_by_records(self._xml_parser, xml_content)

    def _split_js_by_units(self, source_code: str) -> list[dict[str, Any]]:
        return split_js_by_units(self._js_parser, source_code)

    @staticmethod
    def _compute_hash(text: str) -> str:
        return compute_hash(text)

    @staticmethod
    def _xml_element_tag(element_node: Node, source_bytes: bytes) -> Optional[str]:
        return xml_element_tag(element_node, source_bytes)

    @staticmethod
    def _xml_element_attr(
        element_node: Node, source_bytes: bytes, attr_name: str
    ) -> Optional[str]:
        return xml_element_attr(element_node, source_bytes, attr_name)

    @staticmethod
    def _js_unit_name(node: Node, source_bytes: bytes) -> Optional[str]:
        return js_unit_name(node, source_bytes)


__all__ = [
    "CodeLoader",
    "compute_hash",
    "estimate_tokens",
    "extract_module_name",
    "extract_ast_info",
    "find_ast_elements_in_chunk",
    "build_python_file_header",
    "load_python_file_impl",
    "load_python_directory",
    "xml_element_tag",
    "xml_element_attr",
    "split_xml_by_records",
    "load_xml_file_impl",
    "load_xml_directory",
    "_XML_LANGUAGE",
    "_XML_RECORD_TAGS",
    "js_unit_name",
    "split_js_by_units",
    "load_js_file_impl",
    "load_csv_file_impl",
    "load_js_directory",
    "_JS_LANGUAGE",
    "_JS_UNIT_NODE_TYPES",
]