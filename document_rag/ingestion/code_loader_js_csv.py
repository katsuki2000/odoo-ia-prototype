"""
document_rag/ingestion/code_loader_js_csv.py

JavaScript (tree-sitter OWL parsing) and CSV document loaders.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter
from tree_sitter import Language, Node, Parser
import tree_sitter_javascript as tsjs

from document_rag.ingestion.code_loader_common import (
    compute_hash,
    estimate_tokens,
    extract_module_name,
)
from document_rag.ingestion.scan_root import compute_source

logger = logging.getLogger(__name__)

_JS_LANGUAGE = Language(tsjs.language())
_JS_UNIT_NODE_TYPES = {
    "class_declaration",
    "function_declaration",
    "lexical_declaration",
}


def js_unit_name(node: Node, source_bytes: bytes) -> Optional[str]:
    """Extract the name of a class/function/lexical declaration node."""
    if node.type in ("class_declaration", "function_declaration"):
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return source_bytes[name_node.start_byte : name_node.end_byte].decode(
                "utf-8", errors="replace"
            )
        return None

    if node.type == "lexical_declaration":
        for child in node.children:
            if child.type == "variable_declarator":
                name_node = child.child_by_field_name("name")
                if name_node is not None:
                    return source_bytes[
                        name_node.start_byte : name_node.end_byte
                    ].decode("utf-8", errors="replace")
        return None

    return None


def split_js_by_units(js_parser: Parser, source_code: str) -> list[dict[str, Any]]:
    """Split JS source into top-level structural units using tree-sitter."""
    source_bytes = source_code.encode("utf-8")
    tree = js_parser.parse(source_bytes)

    units: list[dict[str, Any]] = []

    for node in tree.root_node.children:
        node_type = node.type
        if node_type == "export_statement":
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
        name = js_unit_name(node, source_bytes)

        unit_type = {
            "class_declaration": "class",
            "function_declaration": "function",
            "lexical_declaration": "lexical",
        }[node_type]

        units.append({"text": text, "unit_type": unit_type, "name": name})

    return units


def load_js_file_impl(
    js_parser: Parser,
    splitter: Any,
    chunk_size: int,
    file_path: str | Path,
    metadata: Optional[dict[str, Any]] = None,
    scan_root: Optional[str | Path] = None,
) -> dict[str, Any]:
    """Load and chunk a JavaScript file using tree-sitter structural parsing."""
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"JavaScript file not found: {file_path}")

    if file_path.suffix != ".js":
        raise ValueError(f"Expected .js file, got {file_path.suffix}")

    logger.info(f"Loading JavaScript file: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        source_code = f.read()

    base_metadata = metadata or {}
    base_metadata.setdefault("source", compute_source(file_path, scan_root))
    base_metadata.setdefault("type", "code_js")
    base_metadata.setdefault("module", extract_module_name(file_path, scan_root))

    units = split_js_by_units(js_parser, source_code)

    chunks: list[str] = []
    chunk_extras: list[dict[str, Any]] = []

    if not units:
        for text in splitter.split_text(source_code):
            chunks.append(text)
            chunk_extras.append({"unit_type": None, "name": None})
    else:
        for unit in units:
            text = unit["text"]
            if estimate_tokens(splitter, text) > chunk_size:
                for sub_text in splitter.split_text(text):
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
                "content_hash": compute_hash(chunk),
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


def load_csv_file_impl(
    chunk_size: int,
    chunk_overlap: int,
    file_path: str | Path,
    metadata: Optional[dict[str, Any]] = None,
    scan_root: Optional[str | Path] = None,
) -> dict[str, Any]:
    """Load and chunk a CSV file (e.g. Odoo ir.model.access.csv)."""
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"CSV file not found: {file_path}")

    logger.info(f"Loading CSV file: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    base_metadata = metadata or {}
    base_metadata.setdefault("source", compute_source(file_path, scan_root))
    base_metadata.setdefault("type", "code_csv")
    base_metadata.setdefault("module", extract_module_name(file_path, scan_root))

    csv_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
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
                "content_hash": compute_hash(chunk),
            }
        )
        metadatas.append(chunk_metadata)

    return {
        "chunks": chunks,
        "metadatas": metadatas,
        "csv_summary": {"total_chunks": len(chunks)},
    }


def load_js_directory(
    directory: str | Path,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
    scan_root: Optional[str | Path] = None,
) -> list[dict[str, Any]]:
    """Load all JavaScript files from a directory."""
    from document_rag.ingestion.code_loader import CodeLoader

    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError(f"Directory not found: {directory}")

    root = Path(scan_root) if scan_root is not None else directory
    loader = CodeLoader(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    documents = []

    for js_file in directory.rglob("*.js"):
        if any(skip in js_file.parts for skip in ("node_modules", "dist", "build", ".git")):
            continue
        try:
            logger.info(f"Processing {js_file.name}...")
            result = loader.load_js_file(js_file, scan_root=root)
            documents.append(result)
        except Exception as e:
            logger.error(f"Error processing {js_file}: {e}")

    logger.info(f"Loaded {len(documents)} JavaScript files from {directory}")
    return documents
