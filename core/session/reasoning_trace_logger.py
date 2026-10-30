"""Append-only JSONL log of the agent's reasoning hops and per-question summaries."""

import datetime
import json
import logging
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from config.settings import OBSERVATION_PREVIEW_CHARS, QUESTION_PREVIEW_CHARS

_logger = logging.getLogger(__name__)

DEFAULT_LOG_PATH = Path(__file__).resolve().parents[2] / "captures" / "reasoning_trace.jsonl"


@dataclass
class ReasoningHop:
    trace_id: str
    hop_index: int
    timestamp: str
    tool_name: str
    tool_args: dict[str, Any]
    observation_summary: str
    elapsed_ms: float


@dataclass
class ReasoningSummary:
    trace_id: str
    timestamp: str
    branch: str
    question_preview: str
    hop_count: int
    llm_call_count: int
    total_time_ms: float
    hop_cap_hit: bool
    fallback_reason: str | None = None
    final_message_preview: str | None = None


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def new_trace_id() -> str:
    return uuid.uuid4().hex[:12]


class ReasoningTraceLogger:
    def __init__(self, log_filepath: Path | None = None):
        self.log_filepath = Path(log_filepath or DEFAULT_LOG_PATH)
        self.log_filepath.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, record_type: str, record: Any) -> None:
        try:
            line = json.dumps({"record_type": record_type, **asdict(record)}, ensure_ascii=False, default=str)
            with open(self.log_filepath, "a", encoding="utf-8") as file:
                file.write(line + "\n")
        except Exception as error:
            _logger.error("Failed to write reasoning trace record: %s", error)

    def _read_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if not self.log_filepath.exists():
            return records
        try:
            with open(self.log_filepath, "r", encoding="utf-8") as file:
                records.extend(json.loads(line) for line in file if line.strip())
        except (OSError, ValueError) as error:
            _logger.error("Failed to read reasoning trace log: %s", error)
        return records

    def log_hop(
        self,
        trace_id: str,
        hop_index: int,
        tool_name: str,
        tool_args: dict[str, Any],
        observation: str,
        elapsed_ms: float,
    ) -> ReasoningHop:
        hop = ReasoningHop(
            trace_id=trace_id,
            hop_index=hop_index,
            timestamp=_now(),
            tool_name=tool_name,
            tool_args=tool_args,
            observation_summary=(observation or "")[:OBSERVATION_PREVIEW_CHARS],
            elapsed_ms=round(elapsed_ms, 3),
        )
        self._write("HOP", hop)
        _logger.info("Reasoning hop [%s] #%d: %s(%s) -> %.2fms", trace_id, hop_index, tool_name, tool_args, elapsed_ms)
        return hop

    def log_summary(
        self,
        trace_id: str,
        branch: str,
        question: str,
        hop_count: int,
        llm_call_count: int,
        total_time_ms: float,
        hop_cap: int | None = None,
        fallback_reason: str | None = None,
        final_message_preview: str | None = None,
    ) -> ReasoningSummary:
        summary = ReasoningSummary(
            trace_id=trace_id,
            timestamp=_now(),
            branch=branch,
            question_preview=(question or "")[:QUESTION_PREVIEW_CHARS],
            hop_count=hop_count,
            llm_call_count=llm_call_count,
            total_time_ms=round(total_time_ms, 3),
            hop_cap_hit=hop_cap is not None and hop_count >= hop_cap,
            fallback_reason=fallback_reason,
            final_message_preview=final_message_preview,
        )
        self._write("SUMMARY", summary)
        _logger.info(
            "Reasoning trace [%s] SUMMARY: branch=%s hops=%d/%s llm_calls=%d total=%.2fms fallback=%s",
            trace_id, branch, hop_count, hop_cap, llm_call_count, total_time_ms, fallback_reason,
        )
        return summary

    def read_recent(self, limit: int = 20, record_type: str | None = None) -> list[dict[str, Any]]:
        records = [r for r in self._read_records() if record_type is None or r.get("record_type") == record_type]
        return records[-limit:]

    def read_trace(self, trace_id: str) -> list[dict[str, Any]]:
        return [r for r in self._read_records() if r.get("trace_id") == trace_id]
