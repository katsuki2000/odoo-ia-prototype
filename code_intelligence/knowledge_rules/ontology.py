"""
code_intelligence/knowledge_rules/ontology.py

Semantic Ontology -- behavioral/technical tags and their query/coverage
helpers (Bloc P2). Regroupe (todo/contexte.txt, chantier de reduction du
nombre de sous-paquets de knowledge_rules/) les anciens tags.py/query.py/
coverage.py de l'ex-paquet ontology/ en un seul module plat, sans
changement de logique.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx

# === tags (ex ontology/tags.py) =============================================


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


# === query (ex ontology/query.py) ===========================================

# Gives the 5 composite tools a single place to ask "which nodes related to
# this model carry tag X", instead of each one re-implementing its own
# node-to-model traversal. Same rationale as find_model_source_filepaths/
# find_server_action_nodes in ci_agent_tools.py : one lookup, not N
# divergent copies of it.
#
# Deliberately does NOT change the dispatch logic in core/routing.py or
# core/graph.py, nor any existing tool's summary_text wording -- this is an
# additive query helper only, wired into new (default-empty) dataclass
# fields on the 5 composite tools' result types, per the Jour 4 mandate
# ("sans casser le dispatch force existant").

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
    ServerAction, which never gets a behavioral tag per Jour 2-3's
    "don't guess" rule -- is excluded from this unfiltered case, since an
    empty-tags node has nothing to report).

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


# === coverage =====================================


NODE_TYPES_NEVER_TAGGED = frozenset({"Module", "Group", "Menu", "WorkflowState"})

# Node types that always receive a technical tag, but are deliberately
# never given a behavioral tag. A node of these types found WITHOUT its expected
# technical tag is a real regression (see detect_unexpected_gaps below).
NODE_TYPES_TECHNICAL_ONLY_BY_DESIGN: Dict[str, str] = {
    "ServerAction": "server_action",
    "AutomationRule": "cron",
}

# Node types that always receive both a behavioral and a technical tag,
# unconditionally, on every instance. A node of these types
# found with zero tags is a real regression.
NODE_TYPES_ALWAYS_FULLY_TAGGED = frozenset({"Rule", "AccessEntry"})

# Node types tagged only conditionally (Field: compute=; Method:
# has_group()+raise or @api.constrains; Model: state field). An untagged
# instance is the expected common case here, not a gap -- excluded from
# detect_unexpected_gaps entirely, covered only by the aggregate counts
# in compute_ontology_coverage.
NODE_TYPES_CONDITIONALLY_TAGGED = frozenset({"Model", "Field", "Method"})


def compute_ontology_coverage(G: nx.DiGraph) -> Dict[str, Dict[str, int]]:
    """
    Per-node_type tally of tag coverage across every node currently in G.

    Returns {node_type: {"total", "tagged_behavioral", "tagged_technical",
    "tagged_any", "untagged"}}. A node_type absent from G is simply absent
    from the returned dict (not reported as zero) -- callers checking
    "did every known node_type get built at all" should check dict keys
    against a corpus-appropriate expectation themselves, not rely on this
    function to know what SHOULD have been built.
    """
    coverage: Dict[str, Dict[str, int]] = {}
    for _, attrs in G.nodes(data=True):
        node_type = attrs.get("node_type", "<unknown>")
        stats = coverage.setdefault(
            node_type,
            {"total": 0, "tagged_behavioral": 0, "tagged_technical": 0, "tagged_any": 0, "untagged": 0},
        )
        stats["total"] += 1
        has_behavioral = bool(attrs.get("behavioral_tags"))
        has_technical = bool(attrs.get("technical_tags"))
        if has_behavioral:
            stats["tagged_behavioral"] += 1
        if has_technical:
            stats["tagged_technical"] += 1
        if has_behavioral or has_technical:
            stats["tagged_any"] += 1
        else:
            stats["untagged"] += 1
    return coverage


def detect_unexpected_gaps(G: nx.DiGraph) -> List[Tuple[str, str, str]]:
    """
    Flag nodes whose type/shape says an existing Jour 2-3 rule SHOULD have
    tagged them, but didn't -- a real regression, not a by-design gap.

    Checks only the two categories where "should always be tagged" is
    unconditional and therefore mechanically checkable without re-deriving
    business logic here:
      1. NODE_TYPES_ALWAYS_FULLY_TAGGED (Rule/AccessEntry): every instance
         must carry at least one behavioral AND at least one technical tag.
      2. NODE_TYPES_TECHNICAL_ONLY_BY_DESIGN (ServerAction/AutomationRule):
         every instance must carry its one specific expected technical tag.

    Deliberately does NOT flag NODE_TYPES_CONDITIONALLY_TAGGED
    (Model/Field/Method) instances with zero tags -- an untagged instance
    there is the expected common case (most fields/methods carry no
    special behavior), and re-deriving "should this specific field/method
    have been tagged" here would duplicate graph_builder.py's own tagging
    conditions rather than checking their output.

    Returns a list of (node_id, node_type, reason) tuples -- empty when no
    unexpected gap is found.
    """
    gaps: List[Tuple[str, str, str]] = []
    for node_id, attrs in G.nodes(data=True):
        node_type = attrs.get("node_type", "<unknown>")

        if node_type in NODE_TYPES_ALWAYS_FULLY_TAGGED:
            if not attrs.get("behavioral_tags"):
                gaps.append((node_id, node_type, "expected >=1 behavioral tag, found none"))
            if not attrs.get("technical_tags"):
                gaps.append((node_id, node_type, "expected >=1 technical tag, found none"))

        elif node_type in NODE_TYPES_TECHNICAL_ONLY_BY_DESIGN:
            expected = NODE_TYPES_TECHNICAL_ONLY_BY_DESIGN[node_type]
            if expected not in (attrs.get("technical_tags") or []):
                gaps.append((node_id, node_type, f"expected technical tag '{expected}', found none"))

    return gaps


__all__ = [
    "BehavioralTag",
    "TechnicalTag",
    "tags_for_node_attrs",
    "get_tagged_nodes_for_model",
    "NODE_TYPES_NEVER_TAGGED",
    "NODE_TYPES_TECHNICAL_ONLY_BY_DESIGN",
    "NODE_TYPES_ALWAYS_FULLY_TAGGED",
    "NODE_TYPES_CONDITIONALLY_TAGGED",
    "compute_ontology_coverage",
    "detect_unexpected_gaps",
]
