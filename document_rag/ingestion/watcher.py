"""
File watcher for automated ingestion.

Watches document/code directories, debounces file events, and updates ChromaDB
through the incremental indexing path.
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

from document_rag.ingestion.incremental import SUPPORTED_EXTENSIONS, reindex_if_changed
from document_rag.ingestion.logging_utils import start_timer, write_ingestion_event
from document_rag.vectorstore.chroma_manager import ChromaManager

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:
    FileSystemEventHandler = object
    Observer = None

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOCS_DIR = PROJECT_ROOT / "document_rag/fake_data" / "documents"
# BUGFIX (todo/contexte.txt section 347): was PROJECT_ROOT / "document_rag/
# fake_data/code" -- that directory was removed 2026-08-12 (see BUGFIX
# comment in ingest_all.py), so the watcher was silently watching a code
# path outside the real curated scope (CODE_DIRS, one dir per Odoo module
# under CORE_ADDONS_ROOT/CUSTOM_ADDONS_ROOT). Import the real scope instead
# of hardcoding a second, stale notion of "the code directory".
from document_rag.ingestion.ingest_all import CODE_DIRS as _WATCHED_CODE_DIRS
DEFAULT_CODE_DIR = list(_WATCHED_CODE_DIRS)


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


class DebouncedIngestionHandler(FileSystemEventHandler):
    """Debounced watchdog event handler for create/modify/delete events."""

    def __init__(
        self,
        docs_manager: ChromaManager | None = None,
        code_manager: ChromaManager | None = None,
        debounce_seconds: float = 2.0,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
    ):
        self.docs_manager = docs_manager or ChromaManager(collection_name="odoo_docs")
        self.code_manager = code_manager or ChromaManager(collection_name="odoo_code")
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

    def _manager_for_path(self, path: Path) -> ChromaManager:
        """Route a file path to its docs or code ChromaManager, mirroring incremental.py."""
        if path.suffix.lower() in {".pdf", ".txt", ".md"}:
            return self.docs_manager
        return self.code_manager

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

        try:
            if action == "delete":
                manager = self._manager_for_path(path)
                deleted_count = manager.delete_by_source(key)
                self.last_result = {
                    "deleted_files": [key],
                    "chunks_deleted": deleted_count,
                }
                write_ingestion_event(
                    event_type="watcher_delete",
                    result=self.last_result,
                    started_at=started_at,
                    files_processed=[key],
                )
                logger.info("Watcher deleted source: %s (%d chunks)", key, deleted_count)
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

                target_roots = [path] if not is_directory else [path]
                self.last_result = reindex_if_changed(
                    target_roots,
                    docs_manager=self.docs_manager,
                    code_manager=self.code_manager,
                    chunk_size=self.chunk_size,
                    chunk_overlap=self.chunk_overlap,
                )
                write_ingestion_event(
                    event_type="watcher_upsert",
                    result=self.last_result,
                    started_at=started_at,
                    files_processed=[key],
                )
                logger.info("Watcher indexed source: %s", path)
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


class IngestionWatcher:
    """Manage watchdog observer lifecycle for ingestion directories."""

    def __init__(
        self,
        watched_paths: Iterable[str | Path] | None = None,
        docs_manager: ChromaManager | None = None,
        code_manager: ChromaManager | None = None,
        debounce_seconds: float = 2.0,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
    ):
        if Observer is None:
            raise ImportError("watchdog is required to run ingestion watcher")

        # Section 349 (todo/contexte.txt): decision produit permanente --
        # le watcher de la branche RAG documentaire ne surveille plus le
        # code par defaut (Code Intelligence s'en charge separement).
        # DEFAULT_CODE_DIR reste defini plus haut pour un usage explicite
        # (watched_paths=[...]) mais n'est plus dans le defaut implicite.
        self.watched_paths = [
            Path(path).resolve()
            for path in (watched_paths or [DEFAULT_DOCS_DIR])
        ]
        self.handler = DebouncedIngestionHandler(
            docs_manager=docs_manager,
            code_manager=code_manager,
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


def _is_supported_source(path: Path) -> bool:
    """Return True if the watcher should process this file path."""
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


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
    parser = argparse.ArgumentParser(description="Watch fake_data docs/code and update ChromaDB")
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        # Section 349 (todo/contexte.txt): default changed -- the
        # documentary RAG watcher no longer watches code by default
        # (permanent product decision, mirrors ingest_all.py). Pass
        # explicit paths (including DEFAULT_CODE_DIR entries) to opt back
        # in for a one-off run.
        default=[DEFAULT_DOCS_DIR],
        help="Directories to watch recursively",
    )
    parser.add_argument(
        "--debounce",
        type=float,
        default=2.0,
        help="Seconds to wait after the last file event before processing",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    watcher = IngestionWatcher(watched_paths=args.paths, debounce_seconds=args.debounce)
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
