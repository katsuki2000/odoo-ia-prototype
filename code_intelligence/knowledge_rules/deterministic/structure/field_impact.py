"""
code_intelligence/deterministic/field_impact.py

Multi-hop dependency and downstream impact analysis for computed fields in Odoo models.
"""

from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
import networkx as nx

from code_intelligence.knowledge_rules.deterministic.common import NOT_FOUND_MARKER
from code_intelligence.knowledge_rules.ontology import tags_for_node_attrs
from core.evidence.evidence import Evidence, EvidenceSourceType, make_evidence


@dataclass
class FieldImpactResult:
    field_name: str
    model_name: str
    upstream_triggers: List[str] = field(default_factory=list)
    upstream_trigger_paths: Dict[str, str] = field(default_factory=dict)
    downstream_computed_fields: List[str] = field(default_factory=list)
    propagation_depth: int = 0
    relational_target: Optional[str] = None
    compute_method: Optional[str] = None
    field_tags: List[str] = field(default_factory=list)
    summary_text: str = ""
    # B1 replication of the B0 pilot: structured Evidence produced at the source.
    evidence: List[Evidence] = field(default_factory=list)


def _field_to_short_name(field_node_id: str) -> str:
    """'field:hr.expense.risk_score' -> 'risk_score'."""
    raw = field_node_id.removeprefix("field:")
    return raw.rsplit(".", 1)[-1]


def _bfs_downstream(
    G: nx.DiGraph,
    start_field_node: str,
    max_depth: int = 10,
) -> Tuple[Set[str], int]:
    """
    Multi-hop BFS downstream propagation.
    From a field node, follows:
      in_edges DEPENDS_ON -> method node -> in_edges COMPUTED_BY -> computed field node
    then recurses from each discovered computed field.
    Returns (set_of_downstream_field_node_ids, max_depth_reached).
    """
    visited_fields: Set[str] = set()
    queue: deque = deque()
    queue.append((start_field_node, 0))
    visited_fields.add(start_field_node)
    max_depth_reached = 0

    while queue:
        current_field, depth = queue.popleft()
        if depth >= max_depth:
            continue

        for in_node, _, in_edge_data in G.in_edges(current_field, data=True):
            if in_edge_data.get("edge_type") != "DEPENDS_ON":
                continue
            method_node = in_node
            for comp_node, _, comp_edge_data in G.in_edges(method_node, data=True):
                if comp_edge_data.get("edge_type") != "COMPUTED_BY":
                    continue
                if comp_node not in visited_fields:
                    visited_fields.add(comp_node)
                    next_depth = depth + 1
                    if next_depth > max_depth_reached:
                        max_depth_reached = next_depth
                    queue.append((comp_node, next_depth))

    visited_fields.discard(start_field_node)
    return visited_fields, max_depth_reached


def _collect_upstream_triggers(
    G: nx.DiGraph,
    field_node: str,
) -> Tuple[Set[str], Dict[str, str]]:
    """
    Collect upstream trigger fields for a computed field.
    Returns (set_of_trigger_short_names, dict_of_trigger_short_name -> trigger_path).
    """
    upstream_triggers: Set[str] = set()
    trigger_paths: Dict[str, str] = {}

    for neighbor in G.neighbors(field_node):
        edge_data = G.get_edge_data(field_node, neighbor) or {}
        if edge_data.get("edge_type") != "COMPUTED_BY":
            continue
        method_node = neighbor
        for method_neighbor in G.neighbors(method_node):
            m_edge = G.get_edge_data(method_node, method_neighbor) or {}
            if m_edge.get("edge_type") != "DEPENDS_ON":
                continue
            trig_short = _field_to_short_name(method_neighbor)
            upstream_triggers.add(trig_short)
            trigger_path = m_edge.get("trigger_path")
            if trigger_path and trigger_path != trig_short:
                trigger_paths[trig_short] = trigger_path

    return upstream_triggers, trigger_paths


def _build_field_impact_evidence(
    model_name: str,
    field_name: str,
    upstream_triggers: Set[str],
    upstream_trigger_paths: Dict[str, str],
    downstream_field_nodes: Set[str],
) -> List[Evidence]:
    """
    one Evidence per upstream trigger dependency and one Evidence per downstream computed field.
    """
    evidence: List[Evidence] = []

    for trig in sorted(upstream_triggers):
        trigger_path = upstream_trigger_paths.get(trig, trig)
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"'{model_name}.{field_name}' is recomputed when '{trigger_path}' changes",
            source=f"depends_on:{model_name}.{field_name}:{trig}",
            value=trigger_path,
            confidence="HIGH",
        ))

    for dn in sorted(downstream_field_nodes):
        short_name = _field_to_short_name(dn)
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Changing '{model_name}.{field_name}' triggers recomputation of '{short_name}'",
            source=dn,
            value=short_name,
            confidence="HIGH",
        ))

    return evidence


def field_change_impact(
    G: nx.DiGraph,
    field_name: str,
    model_name: str,
    max_depth: int = 10,
) -> FieldImpactResult:
    """
    Analyzes upstream dependencies and downstream impact of modifying a field.
    Traces COMPUTED_BY, DEPENDS_ON, and RELATES_TO edges on the Knowledge Graph.
    """
    field_node = f"field:{model_name}.{field_name}"

    if field_node not in G:
        return FieldImpactResult(
            field_name=field_name,
            model_name=model_name,
            summary_text=f"Field '{field_name}' on model '{model_name}' {NOT_FOUND_MARKER}."
        )

    f_data = G.nodes[field_node]
    compute_method = f_data.get("compute")
    relational_target = f_data.get("comodel_name")

    upstream_triggers, trigger_paths = _collect_upstream_triggers(G, field_node)
    downstream_field_nodes, depth_reached = _bfs_downstream(G, field_node, max_depth=max_depth)
    downstream_computed_fields: Set[str] = set()
    for dn in downstream_field_nodes:
        downstream_computed_fields.add(_field_to_short_name(dn))

    downstream_str = ", ".join(sorted(downstream_computed_fields)) if downstream_computed_fields else "None"

    upstream_parts: List[str] = []
    for trig in sorted(upstream_triggers):
        if trig in trigger_paths:
            upstream_parts.append(f"{trig} (via {trigger_paths[trig]})")
        else:
            upstream_parts.append(trig)
    upstream_str = ", ".join(upstream_parts) if upstream_parts else "None"

    summary = (
        f"Field '{field_name}' on '{model_name}': "
        f"Triggers recomputation of [{downstream_str}]. "
        f"Depends on [{upstream_str}]."
    )

    return FieldImpactResult(
        field_name=field_name,
        model_name=model_name,
        upstream_triggers=sorted(list(upstream_triggers)),
        upstream_trigger_paths=trigger_paths,
        downstream_computed_fields=sorted(list(downstream_computed_fields)),
        propagation_depth=depth_reached,
        relational_target=relational_target,
        compute_method=compute_method,
        field_tags=tags_for_node_attrs(f_data),
        summary_text=summary,
        evidence=_build_field_impact_evidence(
            model_name, field_name, upstream_triggers, trigger_paths, downstream_field_nodes
        ),
    )
