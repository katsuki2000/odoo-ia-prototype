"""
core/evidence_collector.py

Turn-scoped Evidence accumulator (Bloc B2, todo/contexte.txt section 622).

Bloc B1 wired each of the 24+2 CI/ORM tools to compute a structured
Evidence/List[Evidence] internally, but every public @tool wrapper
discards it before returning (LangChain's @tool contract only lets a
str reach the LLM/ToolMessage -- see tool_call_execution.py's
`str(ctx.tool_map[tool_name].invoke(tool_args))`). This module is the
side-channel that lets a wrapper hand its Evidence off without changing
that return contract: same pattern as erp_data/odoo_context.py's
per-request ContextVars for odoo_uid/odoo_api_key.

Shared kernel: zero dependency on core/evidence.py's Evidence class is
avoided here on purpose (only a runtime type check, no import of the
pydantic model needed) so this module stays importable from any tool
wrapper (CI or ORM side) without risking a cycle.

Lifecycle: start_evidence_collection() once per turn (before the CI/ORM
tool-calling loop starts), record_evidence() from inside each tool
wrapper right before it returns its str, collect_and_clear_evidence()
once per turn (right before format_output() composes AssistantResponse)
to drain the accumulator into AssistantResponse.evidence_dossier.

Same operational risk profile as the existing ContextVars this mirrors:
a context not started/cleared correctly across an async boundary can
leak or lose entries -- not a new risk category introduced by this
module.
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
    turn's accumulator. Normalizes the two shapes produced across the
    codebase: most Bloc B1 tools return List[Evidence], but the two B0
    pilots (get_total_sales_raw, get_order_count_raw) return a single
    Evidence.

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
