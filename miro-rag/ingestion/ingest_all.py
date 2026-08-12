"""
Master ingestion orchestrator for all document types.

Coordinates:
1. PDF loading with OCR detection (ingestion/pdf_loader.py)
2. Python code extraction with AST metadata (ingestion/code_loader.py)
3. XML template/record parsing (ingestion/code_loader.py)
4. Wiki and markdown chunking (ingestion/wiki_loader.py)
5. ChromaDB population with embedding and storage (vectorstore/chroma_manager.py)

Runs full ingestion of fake_data/documents/ (docs) and a curated set of
real Odoo module directories under ADDONS_ROOT (code) to ChromaDB.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Optional

# Add PROJECT_ROOT to python path before imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ingestion.code_loader import CodeLoader, load_python_directory, load_xml_directory, load_js_directory
from ingestion.pdf_loader import PDFLoader, load_pdf_directory
from ingestion.wiki_loader import WikiLoader, load_wiki_directory
from vectorstore.chroma_manager import ChromaManager

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FAKE_DATA_DIR = PROJECT_ROOT / "fake_data"
DOCS_DIR = FAKE_DATA_DIR / "documents"
LOGS_DIR = PROJECT_ROOT / "ingestion" / "logs"

# 2026-08-12: fake_data/code/ (synthetic 3-module stand-in corpus) removed
# by the user -- see contexte.txt / todo/etat_reel.md "sync avec le vrai
# Odoo". This documentary code-RAG branch is deliberately kept pointed at
# a REAL corpus rather than deleted outright: it is the documented
# negative-result baseline for the thesis (RAG documentaire sur du code
# custom s'est avere insuffisant face a la Code Intelligence deterministe
# -- real plan.md Bloc 6). Scoped to the SAME module set as
# rag.graph.get_code_intelligence_graph() (not the full ~700-module
# ADDONS_ROOT) so the two branches are comparable on identical source
# material -- see _documentary_code_module_dirs() below.
ADDONS_ROOT = Path("/home/user/odoo-17.0/addons") if Path("/home/user/odoo-17.0/addons").exists() else PROJECT_ROOT.parent / "addons"
CORE_MODULES_ALWAYS_LOADED = ["account", "sale", "stock"]


def _documentary_code_module_dirs() -> list[Path]:
    """Real-corpus module directories this documentary RAG branch indexes.

    Mirrors rag.graph.get_code_intelligence_graph()'s module scope (core
    Odoo modules + miro_ai + every custom_* adversarial module + each
    custom_* module's DIRECT manifest dependencies, e.g. hr_expense) so the
    documentary and deterministic branches reason over identical source
    material. Duplicated here rather than imported from rag.graph to avoid
    coupling this secondary (intentionally-underperforming, kept as a
    thesis baseline) branch to the tested deterministic graph-building
    code path -- if the two ever need to be kept in lockstep, extract a
    shared helper instead of hand-syncing.
    """
    if not ADDONS_ROOT.exists():
        return []

    from code_intelligence.utils import discover_odoo_modules
    from code_intelligence.manifest_parser import parse_manifest

    dirs: list[Path] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        if name in seen:
            return
        mod_dir = ADDONS_ROOT / name
        if mod_dir.is_dir() and (mod_dir / "__manifest__.py").exists():
            dirs.append(mod_dir)
            seen.add(name)

    for core_name in CORE_MODULES_ALWAYS_LOADED:
        _add(core_name)
    _add("miro_ai")

    custom_modules = discover_odoo_modules(ADDONS_ROOT, prefix="custom_")
    for mod_name in custom_modules:
        _add(mod_name)

    # Direct manifest dependencies only (J36-equivalent, one level deep --
    # not the full transitive closure, same reasoning as rag.graph).
    for mod_name in custom_modules:
        manifest_p = ADDONS_ROOT / mod_name / "__manifest__.py"
        try:
            manifest = parse_manifest(manifest_p)
        except Exception as e:
            logger.error("Documentary scope: failed to parse manifest for '%s': %s", mod_name, e)
            continue
        for dep_name in manifest.depends:
            _add(dep_name)

    return dirs


# Ensure directories exist BEFORE logging setup
LOGS_DIR.mkdir(exist_ok=True, parents=True)
DOCS_DIR.mkdir(exist_ok=True, parents=True)
# NOTE: CODE_DIR is intentionally NOT eagerly created here anymore -- it
# used to be FAKE_DATA_DIR / "code" with an unconditional .mkdir() at
# import time, which silently resurrected an EMPTY fake_data/code/
# directory every time this module was imported, defeating its deletion
# with no error signal at all. See CODE_DIR/CODE_DIRS below.

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "ingestion.log"),
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger(__name__)

# Computed once at import: read-only directory listing + manifest parsing,
# no filesystem mutation (unlike the old CODE_DIR.mkdir()).
CODE_DIRS: list[Path] = _documentary_code_module_dirs()
# Backward-compat sentinel for existing `from ingestion.ingest_all import
# CODE_DIR` call sites and for IngestionOrchestrator.ingest_all()'s own
# `code_dir` parameter default: None means "use the curated real-corpus
# scope in CODE_DIRS above", never a single directory anymore.
CODE_DIR = None


class IngestionOrchestrator:
    """Orchestrates multi-source document ingestion to ChromaDB."""

    def __init__(
        self,
        chroma_db_path: str | Path = "vectorstore/chroma_db",
        collection_name: str = "odoo_documents",
        chunk_size: int = 512,
        chunk_overlap: int = 50,
    ):
        """
        Initialize ingestion orchestrator.

        Args:
            chroma_db_path: Path to ChromaDB storage
            collection_name: Name of ChromaDB collection
            chunk_size: Chunk size for all text splitters
            chunk_overlap: Overlap between chunks
        """
        self.docs_manager = ChromaManager(
            db_path=chroma_db_path,
            collection_name="odoo_docs",
        )
        self.code_manager = ChromaManager(
            db_path=chroma_db_path,
            collection_name="odoo_code",
        )
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        # Statistics
        self.stats = {
            "total_chunks": 0,
            "by_type": {},
            "by_source": {},
            "by_module": {},
            "load_times": {},
        }

        self.last_docs_dir: str | Path = DOCS_DIR
        self.last_code_dir: Optional[str | Path] = CODE_DIR
        self.last_incremental: bool = False

    def ingest_all(
        self,
        docs_dir: str | Path = DOCS_DIR,
        code_dir: Optional[str | Path] = CODE_DIR,
        incremental: bool = False,
    ) -> dict[str, Any]:
        """
        Ingest all documents from docs and code directories.

        Args:
            docs_dir: Path to documents directory (PDFs, wikis)
            code_dir: Path to code directory (Python, XML)
            incremental: Whether to check for changes (not fully implemented)

        Returns:
            Statistics dictionary
        """
        docs_dir_path = Path(docs_dir) if str(docs_dir) != "" else None

        self.last_docs_dir = docs_dir
        self.last_code_dir = code_dir
        self.last_incremental = incremental

        logger.info("=" * 60)
        logger.info("Starting full document ingestion")
        logger.info("=" * 60)

        # Ingest documents
        if docs_dir_path and docs_dir_path.exists():
            logger.info(f"\n[DOCS] Loading from {docs_dir_path}")
            self._ingest_documents_dir(docs_dir_path)
        else:
            logger.warning(f"Docs directory not found or empty: {docs_dir}")

        # Ingest code. Three distinct meanings for code_dir (2026-08-12,
        # fake_data/code/ removal):
        #   None (default)  -> curated real-corpus scope, CODE_DIRS (one
        #                       _ingest_code_dir() call per module dir).
        #   "" (empty str)  -> explicit skip, unchanged pre-existing sentinel
        #                       (see clear_and_reingest()/test_clear_and_reingest).
        #   any other value -> single directory, old rglob-one-dir behavior
        #                       (unchanged, still used directly by tests).
        if code_dir is None:
            if not CODE_DIRS:
                logger.warning(
                    "Documentary code scope resolved to zero modules under "
                    "%s -- nothing ingested. Check ADDONS_ROOT.", ADDONS_ROOT,
                )
            for mod_dir in CODE_DIRS:
                logger.info(f"\n[CODE] Loading module '{mod_dir.name}' from {mod_dir}")
                self._ingest_code_dir(mod_dir)
        elif str(code_dir) == "":
            logger.info("Code ingestion explicitly skipped (code_dir='').")
        else:
            code_dir_path = Path(code_dir)
            if code_dir_path.exists():
                logger.info(f"\n[CODE] Loading from {code_dir_path}")
                self._ingest_code_dir(code_dir_path)
            else:
                logger.warning(f"Code directory not found or empty: {code_dir}")

        # Get final statistics
        docs_stats = self.docs_manager.get_stats()
        code_stats = self.code_manager.get_stats()
        
        from collections import Counter

        final_stats = {
            "total_chunks": docs_stats.get("total_chunks", 0) + code_stats.get("total_chunks", 0),
            "by_type": dict(Counter(docs_stats.get("by_type", {})) + Counter(code_stats.get("by_type", {}))),
            "by_module": dict(Counter(docs_stats.get("by_module", {})) + Counter(code_stats.get("by_module", {}))),
        }
        logger.info("\n" + "=" * 60)
        logger.info("INGESTION COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Total chunks indexed: {final_stats['total_chunks']}")
        logger.info(f"By type: {final_stats['by_type']}")
        logger.info(f"By module: {final_stats['by_module']}")

        return final_stats

    def _ingest_documents_dir(self, docs_dir: Path) -> None:
        """Ingest PDF, markdown, and text files."""
        if not docs_dir.exists():
            logger.warning(f"Docs directory not found: {docs_dir}")
            return

        # Load PDFs
        pdf_files = list(docs_dir.glob("*.pdf"))
        if pdf_files:
            logger.info(f"Found {len(pdf_files)} PDF files")
            start = time.time()
            try:
                self._load_and_ingest_pdfs(docs_dir)
            except Exception as e:
                logger.error(f"Error loading PDFs: {e}")
            elapsed = time.time() - start
            self.stats["load_times"]["pdfs"] = elapsed
            logger.info(f"PDF ingestion took {elapsed:.2f}s")

        # Load wiki/markdown files
        txt_files = list(docs_dir.glob("*.txt"))
        md_files = list(docs_dir.glob("*.md"))
        if txt_files or md_files:
            logger.info(f"Found {len(txt_files)} .txt and {len(md_files)} .md files")
            start = time.time()
            try:
                self._load_and_ingest_wiki(docs_dir)
            except Exception as e:
                logger.error(f"Error loading wiki files: {e}")
            elapsed = time.time() - start
            self.stats["load_times"]["wiki"] = elapsed
            logger.info(f"Wiki ingestion took {elapsed:.2f}s")

    def _ingest_code_dir(self, code_dir: Path) -> None:
        """Ingest Python, XML, and JS code files."""
        if not code_dir.exists():
            logger.warning(f"Code directory not found: {code_dir}")
            return

        # Load Python files
        py_files = list(code_dir.rglob("*.py"))
        if py_files:
            logger.info(f"Found {len(py_files)} Python files")
            start = time.time()
            try:
                self._load_and_ingest_python(code_dir)
            except Exception as e:
                logger.error(f"Error loading Python files: {e}")
            elapsed = time.time() - start
            self.stats["load_times"]["python"] = elapsed
            logger.info(f"Python ingestion took {elapsed:.2f}s")

        # Load XML files
        xml_files = list(code_dir.rglob("*.xml"))
        if xml_files:
            logger.info(f"Found {len(xml_files)} XML files")
            start = time.time()
            try:
                self._load_and_ingest_xml(code_dir)
            except Exception as e:
                logger.error(f"Error loading XML files: {e}")
            elapsed = time.time() - start
            self.stats["load_times"]["xml"] = elapsed
            logger.info(f"XML ingestion took {elapsed:.2f}s")

        # Load JS files
        js_files = list(code_dir.rglob("*.js"))
        if js_files:
            logger.info(f"Found {len(js_files)} JS files")
            start = time.time()
            try:
                self._load_and_ingest_js(code_dir)
            except Exception as e:
                logger.error(f"Error loading JS files: {e}")
            elapsed = time.time() - start
            self.stats["load_times"]["js"] = elapsed
            logger.info(f"JS ingestion took {elapsed:.2f}s")

        # Load CSV files
        csv_files = list(code_dir.rglob("*.csv"))
        if csv_files:
            logger.info(f"Found {len(csv_files)} CSV files")
            start = time.time()
            try:
                self._load_and_ingest_csv(code_dir)
            except Exception as e:
                logger.error(f"Error loading CSV files: {e}")
            elapsed = time.time() - start
            self.stats["load_times"]["csv"] = elapsed
            logger.info(f"CSV ingestion took {elapsed:.2f}s")

    def _load_and_ingest_pdfs(self, docs_dir: Path) -> None:
        """Load and ingest PDF documents."""
        loader = PDFLoader(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

        for pdf_file in docs_dir.glob("*.pdf"):
            try:
                logger.info(f"  Processing: {pdf_file.name}")
                result = loader.load_and_chunk(pdf_file)

                chunks = result["chunks"]
                metadatas = result["metadatas"]
                ocr_used = result["ocr_used"]

                if chunks:
                    ids = self.docs_manager.add_chunks(chunks, metadatas)
                    logger.info(
                        f"    Added {len(ids)} chunks "
                        f"(OCR: {ocr_used})"
                    )

                    # Update statistics
                    self.stats["total_chunks"] += len(chunks)
                    self.stats["by_source"][pdf_file.name] = len(chunks)
                    self.stats["by_type"]["doc_pdf"] = (
                        self.stats["by_type"].get("doc_pdf", 0) + len(chunks)
                    )
                else:
                    logger.warning(f"    No chunks extracted from {pdf_file.name}")

            except Exception as e:
                logger.error(f"  Error processing {pdf_file.name}: {e}")

    def _load_and_ingest_wiki(self, docs_dir: Path) -> None:
        """Load and ingest wiki/markdown documents."""
        loader = WikiLoader(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

        for txt_file in docs_dir.glob("*.txt"):
            try:
                logger.info(f"  Processing: {txt_file.name}")
                result = loader.load_text_file(txt_file)

                chunks = result["chunks"]
                metadatas = result["metadatas"]

                if chunks:
                    ids = self.docs_manager.add_chunks(chunks, metadatas)
                    logger.info(f"    Added {len(ids)} chunks")

                    self.stats["total_chunks"] += len(chunks)
                    self.stats["by_source"][txt_file.name] = len(chunks)
                    self.stats["by_type"]["doc_wiki"] = (
                        self.stats["by_type"].get("doc_wiki", 0) + len(chunks)
                    )

            except Exception as e:
                logger.error(f"  Error processing {txt_file.name}: {e}")

        for md_file in docs_dir.glob("*.md"):
            try:
                logger.info(f"  Processing: {md_file.name}")
                result = loader.load_markdown_file(md_file)

                chunks = result["chunks"]
                metadatas = result["metadatas"]

                if chunks:
                    ids = self.docs_manager.add_chunks(chunks, metadatas)
                    logger.info(f"    Added {len(ids)} chunks")

                    self.stats["total_chunks"] += len(chunks)
                    self.stats["by_source"][md_file.name] = len(chunks)
                    self.stats["by_type"]["doc_wiki"] = (
                        self.stats["by_type"].get("doc_wiki", 0) + len(chunks)
                    )

            except Exception as e:
                logger.error(f"  Error processing {md_file.name}: {e}")

    def _load_and_ingest_python(self, code_dir: Path) -> None:
        """Load and ingest Python code files."""
        loader = CodeLoader(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

        for py_file in code_dir.rglob("*.py"):
            # Skip common non-code directories
            if any(
                skip in part.lower()
                for part in py_file.parts
                for skip in ("__pycache__", "venv", ".venv", ".git", "site-packages", ".pytest_cache")
            ):
                continue

            try:
                logger.info(f"  Processing: {py_file.relative_to(code_dir)}")
                result = loader.load_python_file(py_file)

                chunks = result["chunks"]
                metadatas = result["metadatas"]

                if chunks:
                    ids = self.code_manager.add_chunks(chunks, metadatas)
                    logger.info(f"    Added {len(ids)} chunks")

                    self.stats["total_chunks"] += len(chunks)
                    source_name = py_file.name
                    self.stats["by_source"][source_name] = (
                        self.stats["by_source"].get(source_name, 0) + len(chunks)
                    )

                    # Track by module
                    for metadata in metadatas:
                        module = metadata.get("module", "unknown")
                        self.stats["by_module"][module] = (
                            self.stats["by_module"].get(module, 0) + 1
                        )

                    self.stats["by_type"]["code_python"] = (
                        self.stats["by_type"].get("code_python", 0) + len(chunks)
                    )

            except Exception as e:
                logger.error(f"  Error processing {py_file}: {e}")

    def _load_and_ingest_xml(self, code_dir: Path) -> None:
        """Load and ingest XML code files."""
        loader = CodeLoader(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

        for xml_file in code_dir.rglob("*.xml"):
            # Skip common non-code directories
            if any(
                skip in part.lower()
                for part in xml_file.parts
                for skip in ("__pycache__", "venv", ".venv", ".git", "site-packages", ".pytest_cache")
            ):
                continue
            try:
                logger.info(f"  Processing: {xml_file.relative_to(code_dir)}")
                result = loader.load_xml_file(xml_file)

                chunks = result["chunks"]
                metadatas = result["metadatas"]

                if chunks:
                    ids = self.code_manager.add_chunks(chunks, metadatas)
                    logger.info(f"    Added {len(ids)} chunks")

                    self.stats["total_chunks"] += len(chunks)
                    source_name = xml_file.name
                    self.stats["by_source"][source_name] = (
                        self.stats["by_source"].get(source_name, 0) + len(chunks)
                    )

                    # Track by module
                    for metadata in metadatas:
                        module = metadata.get("module", "unknown")
                        self.stats["by_module"][module] = (
                            self.stats["by_module"].get(module, 0) + 1
                        )

                    self.stats["by_type"]["code_xml"] = (
                        self.stats["by_type"].get("code_xml", 0) + len(chunks)
                    )

            except Exception as e:
                logger.error(f"  Error processing {xml_file}: {e}")

    def _load_and_ingest_js(self, code_dir: Path) -> None:
        """Load and ingest JavaScript code files."""
        loader = CodeLoader(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

        for js_file in code_dir.rglob("*.js"):
            # Skip common non-code directories
            if any(
                skip in part.lower()
                for part in js_file.parts
                for skip in ("node_modules", "dist", "build", ".git")
            ):
                continue
            try:
                logger.info(f"  Processing: {js_file.relative_to(code_dir)}")
                result = loader.load_js_file(js_file)

                chunks = result["chunks"]
                metadatas = result["metadatas"]

                if chunks:
                    ids = self.code_manager.add_chunks(chunks, metadatas)
                    logger.info(f"    Added {len(ids)} chunks")

                    self.stats["total_chunks"] += len(chunks)
                    source_name = js_file.name
                    self.stats["by_source"][source_name] = (
                        self.stats["by_source"].get(source_name, 0) + len(chunks)
                    )

                    # Track by module
                    for metadata in metadatas:
                        module = metadata.get("module", "unknown")
                        self.stats["by_module"][module] = (
                            self.stats["by_module"].get(module, 0) + 1
                        )

                    self.stats["by_type"]["code_js"] = (
                        self.stats["by_type"].get("code_js", 0) + len(chunks)
                    )

            except Exception as e:
                logger.error(f"  Error processing {js_file}: {e}")

    def _load_and_ingest_csv(self, code_dir: Path) -> None:
        """Load and ingest CSV code files."""
        loader = CodeLoader(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

        for csv_file in code_dir.rglob("*.csv"):
            try:
                logger.info(f"  Processing: {csv_file.relative_to(code_dir)}")
                result = loader.load_csv_file(csv_file)

                chunks = result["chunks"]
                metadatas = result["metadatas"]

                if chunks:
                    ids = self.code_manager.add_chunks(chunks, metadatas)
                    logger.info(f"    Added {len(ids)} chunks")

                    self.stats["total_chunks"] += len(chunks)
                    source_name = csv_file.name
                    self.stats["by_source"][source_name] = (
                        self.stats["by_source"].get(source_name, 0) + len(chunks)
                    )

                    # Track by module
                    for metadata in metadatas:
                        module = metadata.get("module", "unknown")
                        self.stats["by_module"][module] = (
                            self.stats["by_module"].get(module, 0) + 1
                        )

                    self.stats["by_type"]["code_csv"] = (
                        self.stats["by_type"].get("code_csv", 0) + len(chunks)
                    )

            except Exception as e:
                logger.error(f"  Error processing {csv_file}: {e}")

    def clear_and_reingest(
        self,
        docs_dir: Optional[str | Path] = None,
        code_dir: Optional[str | Path] = None,
        incremental: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Clear collection and re-ingest all documents."""
        logger.info("Clearing collection...")
        self.docs_manager.delete_collection()
        self.code_manager.delete_collection()
        logger.info("Collection cleared.")

        target_docs = docs_dir if docs_dir is not None else getattr(self, "last_docs_dir", DOCS_DIR)
        target_code = code_dir if code_dir is not None else getattr(self, "last_code_dir", CODE_DIR)
        target_inc = incremental if incremental is not None else getattr(self, "last_incremental", False)

        return self.ingest_all(
            docs_dir=target_docs,
            code_dir=target_code,
            incremental=target_inc,
        )


def main():
    """Main entry point for ingestion."""
    parser = argparse.ArgumentParser(
        description="Ingest all documents into ChromaDB"
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear collection before ingesting",
    )
    parser.add_argument(
        "--docs-dir",
        type=Path,
        default=DOCS_DIR,
        help="Path to documents directory",
    )
    parser.add_argument(
        "--code-dir",
        type=Path,
        default=CODE_DIR,
        help=(
            "Path to a single code directory to ingest. If omitted, "
            "ingests the curated real-corpus module scope (CODE_DIRS -- "
            "see _documentary_code_module_dirs())."
        ),
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=PROJECT_ROOT / "vectorstore" / "chroma_db",
        help="Path to ChromaDB storage",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=512,
        help="Chunk size for text splitting",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=50,
        help="Overlap between chunks",
    )

    args = parser.parse_args()

    # Initialize orchestrator
    orchestrator = IngestionOrchestrator(
        chroma_db_path=args.db_path,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )

    # Clear if requested
    if args.clear:
        stats = orchestrator.clear_and_reingest()
    else:
        stats = orchestrator.ingest_all(
            docs_dir=args.docs_dir,
            code_dir=args.code_dir,
        )

    # Save statistics
    stats_file = LOGS_DIR / "ingestion_stats.json"
    with open(stats_file, "w") as f:
        json.dump(stats, f, indent=2, default=str)

    logger.info(f"\nStatistics saved to {stats_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
