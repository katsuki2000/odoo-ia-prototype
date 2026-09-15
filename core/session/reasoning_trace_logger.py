"""
core/reasoning_trace_logger.py

Reasoning Path Observability & LLM Call Budget:
Logs the agent's reasoning path, composite tool calls, and LLM call counts to an
append-only JSONL log (`captures/reasoning_trace.jsonl`).
"""

import datetime
import json
import logging
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

_logger = logging.getLogger(__name__)

# Maximum tool hops per question guardrail -- kept in sync with
# code_intelligence.agent.context.CI_MAX_HOPS (raised from 4 to 6, see
# that module's comment for why); test_j46_j48_reasoning_trace.py asserts
# the two never drift apart. Real call sites always pass hop_cap=ctx.hop_cap
# explicitly (postprocess.py) -- this is only the fallback default below.
MAX_HOPS_PER_QUESTION = 6


@dataclass
class ReasoningHop:
    trace_id: str
    hop_index: int
    timestamp: str
    tool_name: str
    tool_args: Dict[str, Any]
    observation_summary: str
    elapsed_ms: float


@dataclass
class ReasoningSummary:
    trace_id: str
    timestamp: str
    branch: str  # "documentaire" | "donnees_erp" | "code_intelligence" | "hybride"
    question_preview: str  # first ~80 chars only -- log hygiene, never the full question
    hop_count: int
    llm_call_count: int
    total_time_ms: float
    hop_cap_hit: bool


class ReasoningTraceLogger:
    """Appends structured per-hop reasoning events + a per-question summary to a JSONL file."""

    def __init__(self, log_filepath: Optional[Path] = None):
        if log_filepath is None:
            log_filepath = Path(__file__).resolve().parent.parent.parent / "captures" / "reasoning_trace.jsonl"
        self.log_filepath = Path(log_filepath)
        self.log_filepath.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, record: dict) -> None:
        try:
            line = json.dumps(record, ensure_ascii=False, default=str)
            with open(self.log_filepath, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception as e:
            _logger.error("Failed to write reasoning trace record: %s", e)

    def log_hop(
        self,
        trace_id: str,
        hop_index: int,
        tool_name: str,
        tool_args: Dict[str, Any],
        observation: str,
        elapsed_ms: float,
    ) -> ReasoningHop:
        hop = ReasoningHop(
            trace_id=trace_id,
            hop_index=hop_index,
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            tool_name=tool_name,
            tool_args=tool_args,
            observation_summary=(observation or "")[:300],
            elapsed_ms=round(elapsed_ms, 3),
        )
        self._write({"record_type": "HOP", **asdict(hop)})
        _logger.info(
            "Reasoning hop [%s] #%d: %s(%s) -> %.2fms",
            trace_id, hop_index, tool_name, tool_args, elapsed_ms,
        )
        return hop

    def log_summary(
        self,
        trace_id: str,
        branch: str,
        question: str,
        hop_count: int,
        llm_call_count: int,
        total_time_ms: float,
        hop_cap: int = MAX_HOPS_PER_QUESTION,
    ) -> ReasoningSummary:
        summary = ReasoningSummary(
            trace_id=trace_id,
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            branch=branch,
            question_preview=(question or "")[:80],
            hop_count=hop_count,
            llm_call_count=llm_call_count,
            total_time_ms=round(total_time_ms, 3),
            hop_cap_hit=hop_count >= hop_cap,
        )
        self._write({"record_type": "SUMMARY", **asdict(summary)})
        _logger.info(
            "Reasoning trace [%s] SUMMARY: branch=%s hops=%d/%d llm_calls=%d total=%.2fms",
            trace_id, branch, hop_count, hop_cap, llm_call_count, total_time_ms,
        )
        return summary

    def read_recent(self, limit: int = 20, record_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Read the N most recent records, optionally filtered to 'HOP' or 'SUMMARY'."""
        if not self.log_filepath.exists():
            return []
        records = []
        try:
            with open(self.log_filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    if record_type is None or rec.get("record_type") == record_type:
                        records.append(rec)
        except Exception as e:
            _logger.error("Failed to read reasoning trace log: %s", e)
        return records[-limit:]

    def read_trace(self, trace_id: str) -> List[Dict[str, Any]]:
        """Read all records (hops + summary) for one specific trace_id, in order -- the
        full post-hoc-debuggable reasoning path for a single question."""
        if not self.log_filepath.exists():
            return []
        records = []
        try:
            with open(self.log_filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    if rec.get("trace_id") == trace_id:
                        records.append(rec)
        except Exception as e:
            _logger.error("Failed to read reasoning trace log: %s", e)
        return records


def new_trace_id() -> str:
    """Short (12-char) uuid4-derived identifier, unique enough per question
    for post-hoc lookup without bloating every JSONL line."""
    return uuid.uuid4().hex[:12]
