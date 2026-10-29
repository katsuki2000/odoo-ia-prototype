"""
core/evidence/evidence_collector.py

Turn-scoped Evidence accumulator.

Each ORM tool wrapper computes a structured List[Evidence], but LangChain's
@tool contract only lets a str reach the LLM/ToolMessage. This module is the
side-channel that lets a wrapper hand its Evidence off without changing that
return contract: same pattern as erp_data/odoo_context.py's per-request
ContextVars.

Shared kernel: it never imports the pydantic Evidence class (only a runtime
type check), so it stays importable from any tool wrapper without risking a
cycle.

Lifecycle: start_evidence_collection() once per turn (query_graph),
record_evidence() from inside each tool wrapper, collect_and_clear_evidence()
once per turn to drain the accumulator into AssistantResponse.evidence_dossier.

Same operational risk profile as the ContextVars this mirrors: a context not
started/cleared correctly across an async boundary can leak or lose entries.
"""

import contextvars
import logging
from typing import Any, List

logger = logging.getLogger(__name__)

_turn_evidence_ctx: "contextvars.ContextVar[List[Any]]" = contextvars.ContextVar(
    "turn_evidence", default=None
)


def start_evidence_collection() -> None:
    """Reset the accumulator to an empty list. Call once at the start of a
    turn, before any tool is invoked."""
    _turn_evidence_ctx.set([])


def record_evidence(evidence: Any) -> None:
    """Append one Evidence, or extend with a List[Evidence], to the current
    turn's accumulator. Accepts either shape: a List[Evidence] (what the ORM
    tools produce) or a single Evidence.

    Silently no-ops (with a warning log) if called before
    start_evidence_collection() -- e.g. a tool invoked outside the normal
    turn lifecycle (a script, a unit test exercising the wrapper directly)
    -- rather than raising, so this never breaks an existing caller that
    doesn't care about the dossier.
    """
    bucket = _turn_evidence_ctx.get()
    if bucket is None:
        logger.warning(
            "record_evidence() called before start_evidence_collection() -- "
            "evidence dropped, no active turn accumulator."
        )
        return
    if isinstance(evidence, list):
        bucket.extend(evidence)
    elif evidence is not None:
        bucket.append(evidence)


def peek_turn_evidence() -> List[Any]:
    """Return a copy of this turn's evidence without draining the accumulator."""
    return list(_turn_evidence_ctx.get() or [])


def collect_and_clear_evidence() -> List[Any]:
    """Drain and return everything recorded this turn, resetting the
    accumulator to None (not []) so a stray record_evidence() call after
    the turn ends is caught by the warning above instead of silently
    starting a new turn's bucket."""
    bucket = _turn_evidence_ctx.get()
    _turn_evidence_ctx.set(None)
    return bucket or []
