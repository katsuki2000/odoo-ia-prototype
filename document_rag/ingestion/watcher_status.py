"""Watcher status schema."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


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
        return asdict(self)
