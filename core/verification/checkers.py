import re
from typing import Optional, Set

import networkx as nx

from core.verification.claims import ClaimType
from core.verification.context import VerificationContext
from core.verification.extractors import Claim

REASON_NO_MATCHING_VALUE = "no_matching_value"
REASON_UNKNOWN_GROUP = "unknown_group"
REASON_NOT_IN_EVIDENCE = "not_in_evidence"
REASON_UNKNOWN_METHOD = "unknown_method"
REASON_NOT_ON_MODEL = "method_not_on_model"


def _contains_token(text: str, token: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(token)}(?!\w)", text) is not None


def _model_closure(graph: nx.DiGraph, model: str) -> Set[str]:
    seen = {model}
    pending = [model]
    while pending:
        current = pending.pop()
        for parent in graph.successors(f"model:{current}"):
            if graph.edges[f"model:{current}", parent].get("edge_type") != "EXTENDS":
                continue
            name = parent.removeprefix("model:")
            if name not in seen:
                seen.add(name)
                pending.append(name)
    return seen


def check_number(claim: Claim, context: VerificationContext) -> Optional[str]:
    for reading in claim.readings:
        tolerance = 0.5 * 10 ** -reading.decimals + 1e-9
        if any(abs(reading.value - known) <= tolerance for known in context.evidence_numbers):
            return None
    return REASON_NO_MATCHING_VALUE


def check_group(claim: Claim, context: VerificationContext) -> Optional[str]:
    if _contains_token(context.evidence_text, claim.key):
        return None
    if context.graph is not None and f"group:{claim.key}" not in context.graph:
        return REASON_UNKNOWN_GROUP
    return REASON_NOT_IN_EVIDENCE


def check_method(claim: Claim, context: VerificationContext) -> Optional[str]:
    if claim.name in context.native_method_names:
        return None
    graph = context.graph
    if claim.owner and graph is not None and f"model:{claim.owner}" in graph:
        on_model = any(
            f"method:{model}.{claim.name}" in graph for model in _model_closure(graph, claim.owner)
        )
        if on_model or _contains_token(context.evidence_text, claim.key):
            return None
        return REASON_NOT_ON_MODEL
    if claim.name in context.graph_method_names or _contains_token(context.evidence_text, claim.name):
        return None
    return REASON_UNKNOWN_METHOD


CHECKERS = {
    ClaimType.NUMBER: check_number,
    ClaimType.GROUP: check_group,
    ClaimType.METHOD: check_method,
}
