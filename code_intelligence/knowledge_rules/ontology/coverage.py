"""
code_intelligence/ontology/coverage.py

Jour 5's mandate is "chaque type de noeud produit par l'extraction a-t-il
au moins un tag ? Detecter les noeuds non couverts par l'ontologie
elle-meme" -- but Jour 2-3 already deliberately leaves some node types (or
some tag dimensions) empty by design, per rules.md Regle 5 ("absence
d'information -> non resolu, jamais devine"):
  - Module, Group, Menu, WorkflowState nodes never receive tag attributes
    at all (no tagging logic was ever written for them in
    graph_builder.py -- not a bug, simply out of Jour 1's closed
    vocabulary scope: none of BehavioralTag/TechnicalTag describes what a
    Module, Group, Menu, or WorkflowState node IS).
  - ServerAction and AutomationRule always get a technical tag but are
    deliberately never given a behavioral tag (their actual business
    intent cannot be determined from what's already extracted without
    guessing).
  - Field and Method nodes are tagged only conditionally (compute=,
    has_group()+raise, @api.constrains) -- an untagged Field/Method is the
    expected, common case (most fields/methods carry no special
    behavior), not a gap.

A flat "100% of nodes must carry >=1 tag" check would therefore be
meaningless noise on this graph. This module instead separates "known,
by-design gap" from "a node whose type/shape says it SHOULD have been
tagged by an existing rule, but wasn't" -- the latter is a real
regression the two functions below are built to catch.
"""

from typing import Any, Dict, List, Tuple

import networkx as nx

# Node types with no tagging logic in graph_builder.py at all (Jour 1's
# closed BehavioralTag/TechnicalTag vocabulary has no slot describing
# what these node types intrinsically are). Always fully untagged --
# expected, not a coverage gap.
NODE_TYPES_NEVER_TAGGED = frozenset({"Module", "Group", "Menu", "WorkflowState"})

# Node types that always receive a technical tag, but are deliberately
# never given a behavioral tag (rules.md Regle 5 -- their actual
# behavioral intent isn't determinable from what's already extracted
# without guessing). A node of these types found WITHOUT its expected
# technical tag is a real regression (see detect_unexpected_gaps below).
NODE_TYPES_TECHNICAL_ONLY_BY_DESIGN: Dict[str, str] = {
    "ServerAction": "server_action",
    "AutomationRule": "cron",
}

# Node types that always receive both a behavioral and a technical tag,
# unconditionally, on every instance (Rule/AccessEntry -- see
# graph_builder.py's _add_security_group_nodes). A node of these types
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
