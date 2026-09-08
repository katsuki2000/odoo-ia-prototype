"""
document_rag/ingestion/code_loader_python.py

Python code document loader with AST parsing for classes, functions, and Odoo models.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Any, Optional

from document_rag.ingestion.code_loader_common import (
    compute_hash,
    extract_module_name,
)
from document_rag.ingestion.scan_root import compute_source

logger = logging.getLogger(__name__)


def extract_ast_info(source_code: str) -> dict[str, Any]:
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
                "odoo_model": None,
                "odoo_inherit": None,
            }
            # Extraire _name = '...' et _inherit = '...' des attributs de classe
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            if target.id == "_name" and isinstance(stmt.value, ast.Constant):
                                class_info["odoo_model"] = stmt.value.value
                            elif target.id == "_inherit":
                                if isinstance(stmt.value, ast.Constant):
                                    class_info["odoo_inherit"] = stmt.value.value
                                elif isinstance(stmt.value, ast.List):
                                    vals = [
                                        elt.value for elt in stmt.value.elts
                                        if isinstance(elt, ast.Constant)
                                    ]
                                    class_info["odoo_inherit"] = ", ".join(vals)
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


def find_ast_elements_in_chunk(
    chunk: str, elements: list[dict[str, Any]]
) -> list[str]:
    """Find which AST elements (classes/functions) are mentioned in a chunk."""
    found = []
    for element in elements:
        name = element.get("name", "")
        if f"class {name}" in chunk or f"def {name}" in chunk:
            found.append(name)
    return found


def build_python_file_header(
    file_path: Path,
    ast_info: dict[str, Any],
    scan_root: Optional[Path] = None,
) -> str:
    """Build a natural-language header summarizing a Python file."""
    parts = []
    module = extract_module_name(file_path, scan_root)
    filename = file_path.name

    parts.append(f"# Fichier: {filename} | Module Odoo: {module}")

    for cls in ast_info.get("classes", []):
        class_name = cls["name"]
        model = cls.get("odoo_model")
        inherit = cls.get("odoo_inherit")

        if model:
            parts.append(f"# Classe {class_name} — modèle Odoo: {model}")
        elif inherit:
            parts.append(f"# Classe {class_name} — hérite de: {inherit}")
        else:
            parts.append(f"# Classe {class_name}")

        methods = cls.get("methods", [])
        if methods:
            parts.append(f"# Méthodes: {', '.join(methods[:10])}")

    return "\n".join(parts) if parts else ""


def load_python_file_impl(
    splitter: Any,
    file_path: str | Path,
    metadata: Optional[dict[str, Any]] = None,
    scan_root: Optional[str | Path] = None,
) -> dict[str, Any]:
    """Load and chunk a Python file with AST metadata."""
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"Python file not found: {file_path}")

    if file_path.suffix != ".py":
        raise ValueError(f"Expected .py file, got {file_path.suffix}")

    logger.info(f"Loading Python file: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        source_code = f.read()

    base_metadata = metadata or {}
    base_metadata.setdefault("source", compute_source(file_path, scan_root))
    base_metadata.setdefault("type", "code_python")
    base_metadata.setdefault("module", extract_module_name(file_path, scan_root))

    ast_info = extract_ast_info(source_code)

    file_header = build_python_file_header(file_path, ast_info, scan_root=scan_root)
    if file_header:
        source_code_with_header = file_header + "\n\n" + source_code
    else:
        source_code_with_header = source_code

    chunks = splitter.split_text(source_code_with_header)
    logger.info(f"Created {len(chunks)} chunks from {file_path}")

    metadatas = []
    for i, chunk in enumerate(chunks):
        chunk_metadata = base_metadata.copy()

        chunk_classes = find_ast_elements_in_chunk(
            chunk, ast_info.get("classes", [])
        )
        chunk_functions = find_ast_elements_in_chunk(
            chunk, ast_info.get("functions", [])
        )

        main_class = ast_info["classes"][0] if ast_info["classes"] else {}

        chunk_metadata.update(
            {
                "chunk_index": i,
                "total_chunks": len(chunks),
                "content_hash": compute_hash(chunk),
                "classes": chunk_classes,
                "functions": chunk_functions,
                "has_docstring": "\"\"\"" in chunk or "'''" in chunk,
                "class_name": main_class.get("name", ""),
                "model_name": main_class.get("odoo_model", "") or main_class.get("odoo_inherit", "") or "",
            }
        )
        metadatas.append(chunk_metadata)

    return {
        "chunks": chunks,
        "metadatas": metadatas,
        "ast_summary": ast_info,
    }


def load_python_directory(
    directory: str | Path,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
    scan_root: Optional[str | Path] = None,
) -> list[dict[str, Any]]:
    """Load all Python files from a directory."""
    from document_rag.ingestion.code_loader import CodeLoader

    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError(f"Directory not found: {directory}")

    root = Path(scan_root) if scan_root is not None else directory
    loader = CodeLoader(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    documents = []

    for py_file in directory.rglob("*.py"):
        if "__pycache__" in py_file.parts or "venv" in py_file.parts:
            continue
        try:
            logger.info(f"Processing {py_file.name}...")
            result = loader.load_python_file(py_file, scan_root=root)
            documents.append(result)
        except Exception as e:
            logger.error(f"Error processing {py_file}: {e}")

    logger.info(f"Loaded {len(documents)} Python files from {directory}")
    return documents
