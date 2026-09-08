"""
document_rag/ingestion/code_loader_xml.py

XML code document loader with tree-sitter parsing for Odoo records and templates.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from tree_sitter import Language, Node, Parser
import tree_sitter_xml as tsxml

from document_rag.ingestion.code_loader_common import (
    compute_hash,
    estimate_tokens,
    extract_module_name,
)
from document_rag.ingestion.scan_root import compute_source

logger = logging.getLogger(__name__)

_XML_LANGUAGE = Language(tsxml.language_xml())
_XML_RECORD_TAGS = {"record", "template"}


def xml_element_tag(element_node: Node, source_bytes: bytes) -> Optional[str]:
    """Return the tag name of an XML element node."""
    for child in element_node.children:
        if child.type in ("STag", "EmptyElemTag"):
            for grandchild in child.children:
                if grandchild.type == "Name":
                    return source_bytes[
                        grandchild.start_byte : grandchild.end_byte
                    ].decode("utf-8", errors="replace")
    return None


def xml_element_attr(
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


def split_xml_by_records(xml_parser: Parser, xml_content: str) -> list[dict[str, Any]]:
    """Split XML content by <record> and <template> element boundaries."""
    source_bytes = xml_content.encode("utf-8")
    tree = xml_parser.parse(source_bytes)

    found: list[dict[str, Any]] = []

    def walk(node: Node) -> None:
        if node.type == "element":
            tag_name = xml_element_tag(node, source_bytes)
            if tag_name in _XML_RECORD_TAGS:
                text = source_bytes[node.start_byte : node.end_byte].decode(
                    "utf-8", errors="replace"
                )
                found.append(
                    {
                        "text": text,
                        "tag": tag_name,
                        "record_id": xml_element_attr(node, source_bytes, "id"),
                    }
                )
                return
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return found


def load_xml_file_impl(
    xml_parser: Parser,
    splitter: Any,
    chunk_size: int,
    file_path: str | Path,
    metadata: Optional[dict[str, Any]] = None,
    scan_root: Optional[str | Path] = None,
) -> dict[str, Any]:
    """Load and chunk an XML file using tree-sitter structural parsing."""
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"XML file not found: {file_path}")

    if file_path.suffix != ".xml":
        raise ValueError(f"Expected .xml file, got {file_path.suffix}")

    logger.info(f"Loading XML file: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        xml_content = f.read()

    base_metadata = metadata or {}
    base_metadata.setdefault("source", compute_source(file_path, scan_root))
    base_metadata.setdefault("type", "code_xml")
    base_metadata.setdefault("module", extract_module_name(file_path, scan_root))

    elements = split_xml_by_records(xml_parser, xml_content)

    chunks: list[str] = []
    chunk_extras: list[dict[str, Any]] = []

    if not elements:
        for text in splitter.split_text(xml_content):
            chunks.append(text)
            chunk_extras.append({"tag": None, "record_id": None})
    else:
        for element in elements:
            text = element["text"]
            if estimate_tokens(splitter, text) > chunk_size:
                for sub_text in splitter.split_text(text):
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
                "content_hash": compute_hash(chunk),
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


def load_xml_directory(
    directory: str | Path,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
    scan_root: Optional[str | Path] = None,
) -> list[dict[str, Any]]:
    """Load all XML files from a directory."""
    from document_rag.ingestion.code_loader import CodeLoader

    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError(f"Directory not found: {directory}")

    root = Path(scan_root) if scan_root is not None else directory
    loader = CodeLoader(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    documents = []

    for xml_file in directory.rglob("*.xml"):
        try:
            logger.info(f"Processing {xml_file.name}...")
            result = loader.load_xml_file(xml_file, scan_root=root)
            documents.append(result)
        except Exception as e:
            logger.error(f"Error processing {xml_file}: {e}")

    logger.info(f"Loaded {len(documents)} XML files from {directory}")
    return documents
