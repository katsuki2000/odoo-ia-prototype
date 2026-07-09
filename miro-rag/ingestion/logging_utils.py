"""
Structured ingestion event logging.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import time
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "ingestion" / "logs"
INGESTION_LOG = LOGS_DIR / "ingestion.log"


def now_iso() -> str:
    """Return the current UTC timestamp as an ISO string."""
    return datetime.now(timezone.utc).isoformat()


def start_timer() -> float:
    """Return a monotonic timestamp for elapsed-time measurement."""
    return time.perf_counter()


def write_ingestion_event(
    event_type: str,
    result: dict[str, Any] | None = None,
    started_at: float | None = None,
    files_processed: list[str] | None = None,
    status: str = "success",
    errors: dict[str, str] | list[str] | None = None,
) -> dict[str, Any]:
    """Append a structured JSON ingestion event to logs/ingestion.log."""
    result = result or {}
    failed_files = result.get("failed_files", {})
    event_errors = errors if errors is not None else failed_files
    final_status = "error" if event_errors else status

    event = {
        "timestamp": now_iso(),
        "event_type": event_type,
        "status": final_status,
        "files_processed": files_processed or _collect_processed_files(result),
        "chunks_added": int(result.get("chunks_added", 0) or 0),
        "chunks_deleted": int(result.get("chunks_deleted", 0) or 0),
        "time_taken_seconds": _elapsed_seconds(started_at),
        "errors": event_errors or {},
        "result": result,
    }

    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(INGESTION_LOG, "a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.error("Failed writing ingestion event log: %s", exc)

    return event


def _elapsed_seconds(started_at: float | None) -> float | None:
    if started_at is None:
        return None

    return round(time.perf_counter() - started_at, 4)


def _collect_processed_files(result: dict[str, Any]) -> list[str]:
    files = []
    for key in ("added_files", "updated_files", "deleted_files", "skipped_files"):
        values = result.get(key, [])
        if values:
            files.extend(str(value) for value in values)

    failed_files = result.get("failed_files", {})
    if isinstance(failed_files, dict):
        files.extend(str(value) for value in failed_files.keys())

    return sorted(set(files))
