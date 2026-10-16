"""Printable reports and e-mail templates attached to a model, with the requester's access verdict."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import networkx as nx

from code_intelligence.agent.node_labels import node_labels
from code_intelligence.rules.group_resolver import format_groups
from core.evidence.evidence import Evidence, EvidenceSourceType, make_evidence

MAX_LISTED_OUTPUTS = 8
REPORT_FORMATS = {"qweb-pdf": "PDF", "qweb-html": "HTML", "qweb-text": "texte"}


@dataclass
class ModelOutputs:
    summary: str = ""
    evidence: List[Evidence] = field(default_factory=list)


def _linked(G: nx.DiGraph, node_id: str, edge_type: str, incoming: bool = False) -> List[str]:
    edges = G.in_edges(node_id, data=True) if incoming else G.out_edges(node_id, data=True)
    return [u if incoming else v for u, v, data in edges if data.get("edge_type") == edge_type]


def _label(data: Dict, fallback: str) -> str:
    return " / ".join(node_labels(data)) or fallback


def _declared_evidence(kind: str, node_id: str, xml_id: str, model_name: str) -> Evidence:
    return make_evidence(
        source_type=EvidenceSourceType.CODE,
        claim=f"{kind} '{xml_id}' is declared on model '{model_name}'",
        source=node_id,
        value=xml_id,
        confidence="HIGH",
    )


def _report_entry(G, node_id, model_name, user_groups, evidence):
    # Deferred import: button_path imports navigation, which imports this module.
    from code_intelligence.rules.button_path import _requester_satisfies_required_groups

    data = G.nodes[node_id]
    xml_id = data.get("xml_id", node_id)
    groups = sorted(group.removeprefix("group:") for group in _linked(G, node_id, "APPLIES_TO_GROUP"))
    details = [
        REPORT_FORMATS.get(data.get("report_type", ""), ""),
        "menu Imprimer" if data.get("binding_model") == model_name else "hors du menu Imprimer de ce modele",
        f"groupes requis [{', '.join(format_groups(G, groups))}]" if groups else "sans restriction de groupe",
    ]
    evidence.append(_declared_evidence("Report", node_id, xml_id, model_name))
    if groups and user_groups is not None:
        available = _requester_satisfies_required_groups(G, groups, user_groups)
        details.append("disponible pour le demandeur" if available else "NON disponible pour le demandeur")
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Report '{xml_id}' is {'available' if available else 'NOT available'} to this requester",
            source=node_id,
            value=available,
            confidence="HIGH",
            scope={"user_groups": sorted(user_groups)},
        ))
    return f"'{_label(data, xml_id)}' ({' ; '.join(detail for detail in details if detail)})"


def _template_entry(G, node_id, model_name, evidence):
    data = G.nodes[node_id]
    xml_id = data.get("xml_id", node_id)
    reports = [_label(G.nodes[report_id], report_id) for report_id in _linked(G, node_id, "ATTACHES_REPORT")]
    evidence.append(_declared_evidence("E-mail template", node_id, xml_id, model_name))
    attached = f" (rapport joint : {', '.join(reports)})" if reports else ""
    return f"'{_label(data, xml_id)}'{attached}"


def _listed(entries: List[str], total: int) -> str:
    hidden = total - len(entries)
    return "; ".join(entries) + (f" (+{hidden} autres)" if hidden > 0 else "")


def describe_model_outputs(G: nx.DiGraph, model_name: str, user_groups: Optional[List[str]] = None) -> ModelOutputs:
    model_node_id = f"model:{model_name}"
    evidence: List[Evidence] = []

    report_ids = sorted(
        _linked(G, model_node_id, "REPORTS_ON", incoming=True),
        key=lambda node_id: (
            G.nodes[node_id].get("binding_model") != model_name,
            bool(_linked(G, node_id, "APPLIES_TO_GROUP")),
            node_id,
        ),
    )
    template_ids = sorted(
        node_id for node_id in _linked(G, model_node_id, "TEMPLATE_FOR", incoming=True)
        if G.nodes[node_id].get("active", True)
    )

    parts = []
    if report_ids:
        entries = [
            _report_entry(G, node_id, model_name, user_groups, evidence)
            for node_id in report_ids[:MAX_LISTED_OUTPUTS]
        ]
        parts.append(f"Rapports imprimables de '{model_name}' : {_listed(entries, len(report_ids))}.")
    if template_ids:
        entries = [
            _template_entry(G, node_id, model_name, evidence)
            for node_id in template_ids[:MAX_LISTED_OUTPUTS]
        ]
        parts.append(f"Modeles d'e-mail de '{model_name}' : {_listed(entries, len(template_ids))}.")
    return ModelOutputs(summary=" ".join(parts), evidence=evidence)
