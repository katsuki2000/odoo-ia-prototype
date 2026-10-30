"""Structured event logging for document ingestion."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import time
from typing import Any

from config.settings import RAG_LOGS_PATH

logger = logging.getLogger(__name__)
LOGS_DIR = Path(RAG_LOGS_PATH)
INGESTION_LOG = LOGS_DIR / "ingestion.log"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def start_timer() -> float:
    return time.perf_counter()


def write_ingestion_event(
    event_type: str,
    result: dict[str, Any] | None = None,
    started_at: float | None = None,
    files_processed: list[str] | None = None,
    status: str = "success",
    errors: dict[str, str] | list[str] | None = None,
) -> dict[str, Any]:
    result = result or {}
    event_errors = errors if errors is not None else result.get("failed_files", {})
    event = {
        "timestamp": now_iso(),
        "event_type": event_type,
        "status": "error" if event_errors else status,
        "files_processed": files_processed or _collect_processed_files(result),
        "chunks_added": int(result.get("chunks_added", 0) or 0),
        "chunks_deleted": int(result.get("chunks_deleted", 0) or 0),
        "time_taken_seconds": _elapsed_seconds(started_at),
        "errors": event_errors or {},
        "result": result,
    }
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with INGESTION_LOG.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("Failed writing ingestion event log")
    return event


def _elapsed_seconds(started_at: float | None) -> float | None:
    return round(time.perf_counter() - started_at, 4) if started_at is not None else None


def _collect_processed_files(result: dict[str, Any]) -> list[str]:
    files = [
        str(path)
        for key in ("added_files", "updated_files", "deleted_files", "skipped_files")
        for path in result.get(key, [])
    ]
    failed = result.get("failed_files", {})
    if isinstance(failed, dict):
        files.extend(map(str, failed))
    return sorted(set(files))
