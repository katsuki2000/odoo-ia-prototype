"""
File watcher for automated multi-tenant ingestion.

Watches per-company document/code directories and routes each file event
to the correct Qdrant collection based on the folder hierarchy:

    fake_data/company_alpha/docs/   → Qdrant collection "company_alpha"
    fake_data/company_alpha/code/   → Qdrant collection "company_alpha"
    fake_data/company_beta/docs/    → Qdrant collection "company_beta"
    fake_data/company_beta/code/    → Qdrant collection "company_beta"

Files that do not match any company folder fall back to ChromaDB (legacy
flat layout), keeping backward compatibility with the existing test suite.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import logging
from pathlib import Path
import signal
import sys
from threading import Lock, Timer
from typing import Any, Iterable

from config.settings import VECTOR_BACKEND
from ingestion.incremental import SUPPORTED_EXTENSIONS, reindex_if_changed
from ingestion.logging_utils import start_timer, write_ingestion_event
from vectorstore.chroma_manager import ChromaManager
from vectorstore.company_collections import (
    collection_for_path,
    get_company_docs_dirs,
    get_manager_for_collection,
)

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:
    FileSystemEventHandler = object
    Observer = None

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOCS_DIR = PROJECT_ROOT / "fake_data" / "documents"
DEFAULT_CODE_DIR = PROJECT_ROOT / "fake_data" / "code"


@dataclass
class WatcherStatus:
    """Runtime status exposed to later API endpoints."""

    watched_paths: list[str]
    watcher_running: bool
    last_event_path: str | None = None
    last_event_type: str | None = None
    last_result: dict[str, Any] | None = None
    errors: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable status payload."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Manager resolution
# ---------------------------------------------------------------------------

def _resolve_manager(file_path: str | Path, chroma_manager: ChromaManager):
    """
    Return the appropriate vector store manager for the given file path.

    When VECTOR_BACKEND is "qdrant" and the path sits under a recognised
    company folder, returns the cached QdrantManager for that collection.
    Otherwise falls back to the supplied ChromaManager (legacy path).

    Returns:
        Tuple of (manager, is_qdrant: bool).
    """
    if VECTOR_BACKEND == "qdrant":
        collection = collection_for_path(file_path)
        if collection:
            return get_manager_for_collection(collection), True

    return chroma_manager, False


# ---------------------------------------------------------------------------
# Debounced event handler
# ---------------------------------------------------------------------------

class DebouncedIngestionHandler(FileSystemEventHandler):
    """Debounced watchdog event handler for create/modify/delete events."""

    def __init__(
        self,
        chroma_manager: ChromaManager | None = None,
        debounce_seconds: float = 2.0,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
    ):
        self.chroma_manager = chroma_manager or ChromaManager()
        self.debounce_seconds = debounce_seconds
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._lock = Lock()
        self._timers: dict[str, Timer] = {}
        self.last_result: dict[str, Any] | None = None
        self.last_event_path: str | None = None
        self.last_event_type: str | None = None
        self.errors: list[str] = []

    def on_created(self, event: Any) -> None:
        """Schedule indexing for a newly created file."""
        self._schedule_event(event, "upsert")

    def on_modified(self, event: Any) -> None:
        """Schedule indexing for a modified file."""
        self._schedule_event(event, "upsert")

    def on_moved(self, event: Any) -> None:
        """Delete old source chunks and index the destination file."""
        src_path = getattr(event, "src_path", "")
        dest_path = getattr(event, "dest_path", "")
        self._schedule_path(src_path, "delete", is_directory=getattr(event, "is_directory", False))
        self._schedule_path(dest_path, "upsert", is_directory=getattr(event, "is_directory", False))

    def on_deleted(self, event: Any) -> None:
        """Schedule deletion for a removed file."""
        self._schedule_event(event, "delete")

    def stop(self) -> None:
        """Cancel pending timers."""
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()

    # ------------------------------------------------------------------
    # Internal scheduling helpers
    # ------------------------------------------------------------------

    def _schedule_event(self, event: Any, action: str) -> None:
        path = getattr(event, "src_path", "")
        is_directory = bool(getattr(event, "is_directory", False))
        self._schedule_path(path, action, is_directory)

    def _schedule_path(self, raw_path: str, action: str, is_directory: bool = False) -> None:
        if not raw_path:
            return

        path = Path(raw_path).resolve()
        if not is_directory and not _is_supported_source(path):
            logger.info("Ignoring unsupported watcher event: %s", path)
            return

        key = str(path)
        process_now = self.debounce_seconds <= 0
        with self._lock:
            previous_timer = self._timers.pop(key, None)
            if previous_timer:
                previous_timer.cancel()

            if not process_now:
                timer = Timer(
                    self.debounce_seconds,
                    self._process_path,
                    args=(path, action, is_directory),
                )
                timer.daemon = True
                self._timers[key] = timer
                timer.start()

        if process_now:
            self._process_path(path, action, is_directory)
            return

        logger.info("Scheduled %s for %s after %.1fs", action, path, self.debounce_seconds)

    def _process_path(self, path: Path, action: str, is_directory: bool = False) -> None:
        started_at = start_timer()
        key = str(path)
        with self._lock:
            self._timers.pop(key, None)

        self.last_event_path = key
        self.last_event_type = action

        # Determine the correct vector store for this file path.
        manager, is_qdrant = _resolve_manager(path, self.chroma_manager)
        backend_label = f"qdrant({manager.collection_name})" if is_qdrant else "chroma"

        try:
            if action == "delete":
                deleted_count = manager.delete_by_source(key)
                self.last_result = {
                    "deleted_files": [key],
                    "chunks_deleted": deleted_count,
                    "backend": backend_label,
                }
                write_ingestion_event(
                    event_type="watcher_delete",
                    result=self.last_result,
                    started_at=started_at,
                    files_processed=[key],
                )
                logger.info(
                    "Watcher deleted source: %s (%d chunks) [%s]",
                    key, deleted_count, backend_label,
                )

            elif action == "upsert":
                if not path.exists():
                    logger.info("Watcher skipped missing source before upsert: %s", path)
                    self.last_result = {"skipped_files": [key]}
                    write_ingestion_event(
                        event_type="watcher_upsert_missing",
                        result=self.last_result,
                        started_at=started_at,
                        files_processed=[key],
                    )
                    return

                self.last_result = reindex_if_changed(
                    [path],
                    chroma_manager=manager,
                    chunk_size=self.chunk_size,
                    chunk_overlap=self.chunk_overlap,
                )
                self.last_result["backend"] = backend_label
                write_ingestion_event(
                    event_type="watcher_upsert",
                    result=self.last_result,
                    started_at=started_at,
                    files_processed=[key],
                )
                logger.info(
                    "Watcher indexed source: %s [%s]", path, backend_label,
                )

            else:
                logger.error("Unexpected watcher action: %s", action)
                self.errors.append(f"Unexpected watcher action: {action}")

        except Exception as exc:
            logger.error("Watcher failed for %s: %s", path, exc)
            self.errors.append(str(exc))
            self.last_result = {"failed_files": {key: str(exc)}}
            write_ingestion_event(
                event_type=f"watcher_{action}",
                result=self.last_result,
                started_at=started_at,
                files_processed=[key],
                status="error",
            )


# ---------------------------------------------------------------------------
# IngestionWatcher: observer lifecycle
# ---------------------------------------------------------------------------

class IngestionWatcher:
    """
    Manage watchdog observer lifecycle for per-company ingestion directories.

    When VECTOR_BACKEND is "qdrant", the default watched paths are the
    company-specific subdirectories under fake_data/ (e.g.
    ``fake_data/company_alpha/docs/``).  The legacy flat layout
    (``fake_data/documents/``, ``fake_data/code/``) is used as fallback
    when no per-company directories are found or when using ChromaDB.
    """

    def __init__(
        self,
        watched_paths: Iterable[str | Path] | None = None,
        chroma_manager: ChromaManager | None = None,
        debounce_seconds: float = 2.0,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
    ):
        if Observer is None:
            raise ImportError("watchdog is required to run ingestion watcher")

        if watched_paths is not None:
            resolved = [Path(p).resolve() for p in watched_paths]
        else:
            resolved = _default_watch_paths()

        self.watched_paths = resolved
        self.handler = DebouncedIngestionHandler(
            chroma_manager=chroma_manager,
            debounce_seconds=debounce_seconds,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        self.observer = Observer()
        self.running = False

    def start(self) -> None:
        """Start watching existing paths recursively."""
        for path in self.watched_paths:
            if not path.exists():
                logger.warning("Watcher path does not exist: %s", path)
                continue
            self.observer.schedule(self.handler, str(path), recursive=True)
            logger.info("Watching ingestion path: %s", path)

        self.observer.start()
        self.running = True

    def stop(self) -> None:
        """Stop observer and pending debounce timers."""
        self.handler.stop()
        if self.running:
            self.observer.stop()
            self.observer.join()
        self.running = False

    def status(self) -> dict[str, Any]:
        """Return current watcher status."""
        return WatcherStatus(
            watched_paths=[str(path) for path in self.watched_paths],
            watcher_running=self.running,
            last_event_path=self.handler.last_event_path,
            last_event_type=self.handler.last_event_type,
            last_result=self.handler.last_result,
            errors=self.handler.errors,
        ).to_dict()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_watch_paths() -> list[Path]:
    """
    Return the default set of directories for the watcher to monitor.

    When VECTOR_BACKEND is "qdrant", prefer the per-company subdirectories
    (fake_data/company_alpha/, fake_data/company_beta/).  Fall back to the
    legacy flat layout when no company dirs are configured.
    """
    if VECTOR_BACKEND == "qdrant":
        company_dirs = get_company_docs_dirs()
        paths: list[Path] = []
        for dir_list in company_dirs.values():
            paths.extend(dir_list)
        if paths:
            return paths

    # Legacy / ChromaDB fallback
    return [DEFAULT_DOCS_DIR, DEFAULT_CODE_DIR]


def _is_supported_source(path: Path) -> bool:
    """Return True if the watcher should process this file path."""
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


# ---------------------------------------------------------------------------
# CLI / daemon entry points
# ---------------------------------------------------------------------------

def run_forever(watched_paths: Iterable[str | Path] | None = None) -> None:
    """Run the watcher until SIGINT/SIGTERM."""
    watcher = IngestionWatcher(watched_paths=watched_paths)
    should_stop = False

    def _handle_signal(signum: int, _frame: Any) -> None:
        nonlocal should_stop
        logger.info("Received signal %s, stopping watcher", signum)
        should_stop = True
        watcher.stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    watcher.start()
    logger.info("Ingestion watcher started")
    while not should_stop:
        signal.pause()


def main() -> int:
    """CLI entry point for the ingestion watcher."""
    parser = argparse.ArgumentParser(
        description=(
            "Watch fake_data company directories and update the correct "
            "Qdrant collection (or ChromaDB) per file path."
        )
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=None,
        help=(
            "Directories to watch recursively. "
            "Defaults to per-company dirs (qdrant) or flat docs/code (chroma)."
        ),
    )
    parser.add_argument(
        "--debounce",
        type=float,
        default=2.0,
        help="Seconds to wait after the last file event before processing",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    watcher = IngestionWatcher(
        watched_paths=args.paths if args.paths else None,
        debounce_seconds=args.debounce,
    )
    try:
        watcher.start()
        logger.info("Ingestion watcher running. Press Ctrl+C to stop.")
        while True:
            signal.pause()
    except KeyboardInterrupt:
        logger.info("Stopping ingestion watcher")
    finally:
        watcher.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
