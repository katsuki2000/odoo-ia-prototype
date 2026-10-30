"""Turn-scoped Evidence accumulator.

LangChain tools can only return a str, so each ORM tool wrapper hands its Evidence over through this
side channel (a ContextVar, like erp_data/odoo_context.py). query_graph starts it once per turn and
drains it into AssistantResponse.evidence_dossier.
"""

import contextvars
import logging
from typing import Any

logger = logging.getLogger(__name__)

_turn_evidence_ctx: contextvars.ContextVar[list[Any] | None] = contextvars.ContextVar("turn_evidence", default=None)


def start_evidence_collection() -> None:
    _turn_evidence_ctx.set([])


def record_evidence(evidence: Any) -> None:
    """Add one Evidence or a list of them; dropped with a warning outside a started turn."""
    bucket = _turn_evidence_ctx.get()
    if bucket is None:
        logger.warning("record_evidence() called before start_evidence_collection(): evidence dropped.")
        return
    if isinstance(evidence, list):
        bucket.extend(evidence)
    elif evidence is not None:
        bucket.append(evidence)


def peek_turn_evidence() -> list[Any]:
    """This turn's evidence, without draining it."""
    return list(_turn_evidence_ctx.get() or [])


def collect_and_clear_evidence() -> list[Any]:
    """Drain this turn's evidence; the accumulator goes back to None so a late record_evidence() is reported."""
    bucket = _turn_evidence_ctx.get()
    _turn_evidence_ctx.set(None)
    return bucket or []
