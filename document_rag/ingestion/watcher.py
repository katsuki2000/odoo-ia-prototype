"""
File watcher for automated ingestion into ChromaDB.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import signal
import sys
from threading import Lock, Timer
from typing import Any, Iterable

from config.settings import RAG_CHUNK_OVERLAP, RAG_CHUNK_SIZE
from document_rag.ingestion.file_formats import is_supported_document
from document_rag.ingestion.incremental import reindex_if_changed
from document_rag.ingestion.ingest_config import DOCS_DIR
from document_rag.ingestion.logging_utils import start_timer, write_ingestion_event
from document_rag.vectorstore.chroma_manager import ChromaManager

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:
    FileSystemEventHandler = object
    Observer = None

logger = logging.getLogger(__name__)

DEFAULT_DOCS_DIR = DOCS_DIR


from document_rag.ingestion.watcher_status import WatcherStatus


class DebouncedIngestionHandler(FileSystemEventHandler):
    """Debounced watchdog event handler for create/modify/delete events."""

    def __init__(
        self,
        docs_manager: ChromaManager | None = None,
        debounce_seconds: float = 2.0,
        chunk_size: int = RAG_CHUNK_SIZE,
        chunk_overlap: int = RAG_CHUNK_OVERLAP,
    ):
        self.docs_manager = docs_manager or ChromaManager()
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
        self._schedule_event(event, "upsert")

    def on_modified(self, event: Any) -> None:
        self._schedule_event(event, "upsert")

    def on_moved(self, event: Any) -> None:
        src_path = getattr(event, "src_path", "")
        dest_path = getattr(event, "dest_path", "")
        self._schedule_path(src_path, "delete", is_directory=getattr(event, "is_directory", False))
        self._schedule_path(dest_path, "upsert", is_directory=getattr(event, "is_directory", False))

    def on_deleted(self, event: Any) -> None:
        self._schedule_event(event, "delete")

    def stop(self) -> None:
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()

    def _manager_for_path(self, path: Path) -> ChromaManager:
        return self.docs_manager

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

                target_roots = [path]
                self.last_result = reindex_if_changed(
                    target_roots,
                    docs_manager=self.docs_manager,
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
        debounce_seconds: float = 2.0,
        chunk_size: int = RAG_CHUNK_SIZE,
        chunk_overlap: int = RAG_CHUNK_OVERLAP,
    ):
        if Observer is None:
            raise ImportError("watchdog is required to run ingestion watcher")

        self.watched_paths = [
            Path(path).resolve()
            for path in (watched_paths or [DEFAULT_DOCS_DIR])
        ]
        self.handler = DebouncedIngestionHandler(
            docs_manager=docs_manager,
            debounce_seconds=debounce_seconds,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        self.observer = Observer()
        self.running = False

    def start(self) -> None:
        for path in self.watched_paths:
            if not path.exists():
                logger.warning("Watcher path does not exist: %s", path)
                continue
            self.observer.schedule(self.handler, str(path), recursive=True)
            logger.info("Watching ingestion path: %s", path)

        self.observer.start()
        self.running = True

    def stop(self) -> None:
        self.handler.stop()
        if self.running:
            self.observer.stop()
            self.observer.join()
        self.running = False

    def status(self) -> dict[str, Any]:
        return WatcherStatus(
            watched_paths=[str(path) for path in self.watched_paths],
            watcher_running=self.running,
            last_event_path=self.handler.last_event_path,
            last_event_type=self.handler.last_event_type,
            last_result=self.handler.last_result,
            errors=self.handler.errors,
        ).to_dict()


def _is_supported_source(path: Path) -> bool:
    return is_supported_document(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Watch docs and update ChromaDB")
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
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
