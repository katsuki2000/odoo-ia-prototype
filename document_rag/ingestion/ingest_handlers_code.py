"""
document_rag/ingestion/ingest_handlers_code.py

Code-type ingestion handlers for Python, XML, JavaScript, and CSV files.
"""

from __future__ import annotations

import logging
from pathlib import Path
import sys
import time
from typing import Any, Optional

from document_rag.ingestion.code_loader import CodeLoader
from document_rag.ingestion.ingest_config import (
    CORE_ADDONS_ROOT,
    CUSTOM_ADDONS_ROOT,
)
from document_rag.ingestion.scan_root import resolve_scan_root

logger = logging.getLogger(__name__)


def load_and_ingest_python(
    loader_cls: Any,
    code_manager: Any,
    stats: dict[str, Any],
    code_dir: Path,
    chunk_size: int,
    chunk_overlap: int,
    scan_root: Optional[Path] = None,
) -> None:
    """Load and ingest Python code files."""
    loader = loader_cls(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    for py_file in code_dir.rglob("*.py"):
        if any(
            skip in part.lower()
            for part in py_file.parts
            for skip in ("__pycache__", "venv", ".venv", ".git", "site-packages", ".pytest_cache")
        ):
            continue

        try:
            logger.info(f"  Processing: {py_file.relative_to(code_dir)}")
            result = loader.load_python_file(py_file, scan_root=scan_root)

            chunks = result["chunks"]
            metadatas = result["metadatas"]

            if chunks:
                ids = code_manager.add_chunks(chunks, metadatas)
                logger.info(f"    Added {len(ids)} chunks")

                stats["total_chunks"] += len(chunks)
                source_name = py_file.name
                stats["by_source"][source_name] = (
                    stats["by_source"].get(source_name, 0) + len(chunks)
                )

                for metadata in metadatas:
                    module = metadata.get("module", "unknown")
                    stats["by_module"][module] = (
                        stats["by_module"].get(module, 0) + 1
                    )

                stats["by_type"]["code_python"] = (
                    stats["by_type"].get("code_python", 0) + len(chunks)
                )

        except Exception as e:
            logger.error(f"  Error processing {py_file}: {e}")


def load_and_ingest_xml(
    loader_cls: Any,
    code_manager: Any,
    stats: dict[str, Any],
    code_dir: Path,
    chunk_size: int,
    chunk_overlap: int,
    scan_root: Optional[Path] = None,
) -> None:
    """Load and ingest XML code files."""
    loader = loader_cls(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    for xml_file in code_dir.rglob("*.xml"):
        if any(
            skip in part.lower()
            for part in xml_file.parts
            for skip in ("__pycache__", "venv", ".venv", ".git", "site-packages", ".pytest_cache")
        ):
            continue
        try:
            logger.info(f"  Processing: {xml_file.relative_to(code_dir)}")
            result = loader.load_xml_file(xml_file, scan_root=scan_root)

            chunks = result["chunks"]
            metadatas = result["metadatas"]

            if chunks:
                ids = code_manager.add_chunks(chunks, metadatas)
                logger.info(f"    Added {len(ids)} chunks")

                stats["total_chunks"] += len(chunks)
                source_name = xml_file.name
                stats["by_source"][source_name] = (
                    stats["by_source"].get(source_name, 0) + len(chunks)
                )

                for metadata in metadatas:
                    module = metadata.get("module", "unknown")
                    stats["by_module"][module] = (
                        stats["by_module"].get(module, 0) + 1
                    )

                stats["by_type"]["code_xml"] = (
                    stats["by_type"].get("code_xml", 0) + len(chunks)
                )

        except Exception as e:
            logger.error(f"  Error processing {xml_file}: {e}")


def load_and_ingest_js(
    loader_cls: Any,
    code_manager: Any,
    stats: dict[str, Any],
    code_dir: Path,
    chunk_size: int,
    chunk_overlap: int,
    scan_root: Optional[Path] = None,
) -> None:
    """Load and ingest JavaScript code files."""
    loader = loader_cls(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    for js_file in code_dir.rglob("*.js"):
        if any(
            skip in part.lower()
            for part in js_file.parts
            for skip in ("node_modules", "dist", "build", ".git")
        ):
            continue
        try:
            logger.info(f"  Processing: {js_file.relative_to(code_dir)}")
            result = loader.load_js_file(js_file, scan_root=scan_root)

            chunks = result["chunks"]
            metadatas = result["metadatas"]

            if chunks:
                ids = code_manager.add_chunks(chunks, metadatas)
                logger.info(f"    Added {len(ids)} chunks")

                stats["total_chunks"] += len(chunks)
                source_name = js_file.name
                stats["by_source"][source_name] = (
                    stats["by_source"].get(source_name, 0) + len(chunks)
                )

                for metadata in metadatas:
                    module = metadata.get("module", "unknown")
                    stats["by_module"][module] = (
                        stats["by_module"].get(module, 0) + 1
                    )

                stats["by_type"]["code_js"] = (
                    stats["by_type"].get("code_js", 0) + len(chunks)
                )

        except Exception as e:
            logger.error(f"  Error processing {js_file}: {e}")


def load_and_ingest_csv(
    loader_cls: Any,
    code_manager: Any,
    stats: dict[str, Any],
    code_dir: Path,
    chunk_size: int,
    chunk_overlap: int,
    scan_root: Optional[Path] = None,
) -> None:
    """Load and ingest CSV code files."""
    loader = loader_cls(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    for csv_file in code_dir.rglob("*.csv"):
        try:
            logger.info(f"  Processing: {csv_file.relative_to(code_dir)}")
            result = loader.load_csv_file(csv_file, scan_root=scan_root)

            chunks = result["chunks"]
            metadatas = result["metadatas"]

            if chunks:
                ids = code_manager.add_chunks(chunks, metadatas)
                logger.info(f"    Added {len(ids)} chunks")

                stats["total_chunks"] += len(chunks)
                source_name = csv_file.name
                stats["by_source"][source_name] = (
                    stats["by_source"].get(source_name, 0) + len(chunks)
                )

                for metadata in metadatas:
                    module = metadata.get("module", "unknown")
                    stats["by_module"][module] = (
                        stats["by_module"].get(module, 0) + 1
                    )

                stats["by_type"]["code_csv"] = (
                    stats["by_type"].get("code_csv", 0) + len(chunks)
                )

        except Exception as e:
            logger.error(f"  Error processing {csv_file}: {e}")


def ingest_code_dir(
    code_dir: Path,
    code_manager: Any,
    stats: dict[str, Any],
    chunk_size: int,
    chunk_overlap: int,
) -> None:
    """Ingest Python, XML, and JS code files from a code directory."""
    if not code_dir.exists():
        logger.warning(f"Code directory not found: {code_dir}")
        return

    scan_root = resolve_scan_root(code_dir, [CORE_ADDONS_ROOT, CUSTOM_ADDONS_ROOT]) or code_dir

    target_mod = sys.modules.get("document_rag.ingestion.ingest_all")
    code_loader_cls = getattr(target_mod, "CodeLoader", CodeLoader) if target_mod else CodeLoader

    py_files = list(code_dir.rglob("*.py"))
    if py_files:
        logger.info(f"Found {len(py_files)} Python files")
        start = time.time()
        try:
            load_and_ingest_python(
                code_loader_cls, code_manager, stats, code_dir, chunk_size, chunk_overlap, scan_root=scan_root
            )
        except Exception as e:
            logger.error(f"Error loading Python files: {e}")
        elapsed = time.time() - start
        stats["load_times"]["python"] = elapsed
        logger.info(f"Python ingestion took {elapsed:.2f}s")

    xml_files = list(code_dir.rglob("*.xml"))
    if xml_files:
        logger.info(f"Found {len(xml_files)} XML files")
        start = time.time()
        try:
            load_and_ingest_xml(
                code_loader_cls, code_manager, stats, code_dir, chunk_size, chunk_overlap, scan_root=scan_root
            )
        except Exception as e:
            logger.error(f"Error loading XML files: {e}")
        elapsed = time.time() - start
        stats["load_times"]["xml"] = elapsed
        logger.info(f"XML ingestion took {elapsed:.2f}s")

    js_files = list(code_dir.rglob("*.js"))
    if js_files:
        logger.info(f"Found {len(js_files)} JS files")
        start = time.time()
        try:
            load_and_ingest_js(
                code_loader_cls, code_manager, stats, code_dir, chunk_size, chunk_overlap, scan_root=scan_root
            )
        except Exception as e:
            logger.error(f"Error loading JS files: {e}")
        elapsed = time.time() - start
        stats["load_times"]["js"] = elapsed
        logger.info(f"JS ingestion took {elapsed:.2f}s")

    csv_files = list(code_dir.rglob("*.csv"))
    if csv_files:
        logger.info(f"Found {len(csv_files)} CSV files")
        start = time.time()
        try:
            load_and_ingest_csv(
                code_loader_cls, code_manager, stats, code_dir, chunk_size, chunk_overlap, scan_root=scan_root
            )
        except Exception as e:
            logger.error(f"Error loading CSV files: {e}")
        elapsed = time.time() - start
        stats["load_times"]["csv"] = elapsed
        logger.info(f"CSV ingestion took {elapsed:.2f}s")
