"""
code_intelligence/knowledge_rules/ontology.py

Semantic Ontology
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx

# === tags =============================================


class BehavioralTag(str, Enum):
    """What a piece of Odoo logic does, from a business-visible standpoint."""

    VISIBILITY_RULE = "visibility_rule"
    BLOCKING_RULE = "blocking_rule"
    CALCULATION_RULE = "calculation_rule"
    WORKFLOW_RULE = "workflow_rule"
    APPROVAL_RULE = "approval_rule"
    NOTIFICATION_RULE = "notification_rule"


class TechnicalTag(str, Enum):
    """Which concrete Odoo mechanism implements the behavior."""

    RECORD_RULE = "record_rule"
    ACL = "acl"
    CONSTRAINT = "constraint"
    COMPUTED_FIELD = "computed_field"
    SERVER_ACTION = "server_action"
    CRON = "cron"


# === query ===========================================

# Gives the 5 composite tools a single place to ask "which nodes related to
# this model carry tag X", instead of each one re-implementing its own
# node-to-model traversal. Same rationale as find_model_source_filepaths/
# find_server_action_nodes in ci_agent_tools.py : one lookup, not N
# divergent copies of it.


# Edge types that connect a Model node to a node worth tag-querying,
# and which side of the edge the Model sits on for each.
_OUT_EDGE_TYPES_FROM_MODEL = {"RESTRICTED_BY", "GRANTED_BY", "HAS_FIELD"}
_IN_EDGE_TYPES_TO_MODEL = {"TARGETS_MODEL", "TRIGGERED_BY"}


def tags_for_node_attrs(attrs: Dict[str, Any]) -> List[str]:
    """Combined behavioral+technical tag values for one node's attrs.
    Public (not a leading-underscore helper) because deterministic_tools.py
    reuses it directly to populate the tag fields added to the 5 composite
    tools' result dataclasses, rather than re-concatenating the same two
    attribute reads at each call site."""
    return list(attrs.get("behavioral_tags", [])) + list(attrs.get("technical_tags", []))


def get_tagged_nodes_for_model(
    G: nx.DiGraph,
    model_name: str,
    behavioral_tag: Optional[str] = None,
    technical_tag: Optional[str] = None,
) -> List[Tuple[str, Dict[str, Any]]]:
    """
    Return (node_id, attrs) for every node semantically related to
    `model_name` that carries the requested tag(s).

    Related nodes considered: the Model node itself, its Rule nodes
    (RESTRICTED_BY), AccessEntry nodes (GRANTED_BY), Field nodes
    (HAS_FIELD), Method nodes (matched by their `model` attribute -- no
    direct graph edge links a Model to its Method nodes), ServerAction
    nodes (TARGETS_MODEL), and AutomationRule nodes (TRIGGERED_BY).

    behavioral_tag/technical_tag take a BehavioralTag/TechnicalTag string
    value (e.g. "approval_rule", "acl"). Both are optional and AND-ed when
    both given. With neither given, every related node carrying at least
    one tag of either kind is returned (an untagged node -- e.g. a
    ServerAction

    Returns [] if model_name is not indexed, without raising -- same
    "absence of information is not an error" convention as every other
    read-only lookup in this codebase.
    """
    model_node = f"model:{model_name}"
    if model_node not in G:
        return []

    candidate_ids: List[str] = [model_node]

    for _, neighbor, edge_data in G.out_edges(model_node, data=True):
        if edge_data.get("edge_type") in _OUT_EDGE_TYPES_FROM_MODEL:
            candidate_ids.append(neighbor)

    for neighbor, _, edge_data in G.in_edges(model_node, data=True):
        if edge_data.get("edge_type") in _IN_EDGE_TYPES_TO_MODEL:
            candidate_ids.append(neighbor)

    # Method nodes carry no direct edge to their Model node (only an
    # attribute) -- matched by attrs scan, same approach already used by
    # find_methods_with_override_cascade in ci_agent_tools.py.
    for node, attrs in G.nodes(data=True):
        if attrs.get("node_type") == "Method" and attrs.get("model") == model_name:
            candidate_ids.append(node)

    results: List[Tuple[str, Dict[str, Any]]] = []
    seen = set()
    for node_id in candidate_ids:
        if node_id in seen or node_id not in G:
            continue
        seen.add(node_id)

        attrs = G.nodes[node_id]
        behavioral = attrs.get("behavioral_tags", [])
        technical = attrs.get("technical_tags", [])

        if behavioral_tag is not None and behavioral_tag not in behavioral:
            continue
        if technical_tag is not None and technical_tag not in technical:
            continue
        if behavioral_tag is None and technical_tag is None and not tags_for_node_attrs(attrs):
            continue

        results.append((node_id, attrs))

    return results



__all__ = [
    "BehavioralTag",
    "TechnicalTag",
    "tags_for_node_attrs",
    "get_tagged_nodes_for_model",
]

