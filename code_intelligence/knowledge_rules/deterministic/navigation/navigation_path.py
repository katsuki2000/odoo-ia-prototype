"""
code_intelligence/deterministic/navigation_path.py

menu -> action -> vue -> bouton navigation
path for "comment faire pour X" questions. Reuses the Menu/Model/Button
sub-graph already built by extraction (ir.ui.menu, ir.actions.act_window,
form view buttons) -- no OWL/JS analysis"aucun chemin UI" triage criterion.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import networkx as nx

from code_intelligence.knowledge_rules.deterministic.navigation.button_path import (
    _requester_satisfies_required_groups,
    button_execution_path,
)
from code_intelligence.knowledge_rules.deterministic.navigation.button_path_models import ButtonExecutionPathResult
from code_intelligence.knowledge_rules.deterministic.common import NOT_FOUND_MARKER, QueryStatus
from code_intelligence.utils import format_file_link, format_xml_id_citations
from core.evidence import Evidence, EvidenceSourceType, make_evidence


@dataclass
class NavigationPathResult:
    model_name: str
    button_identifier: str = ""
    status: QueryStatus = QueryStatus.NOT_FOUND
    menu_breadcrumb: List[str] = field(default_factory=list)
    menu_xml_id: str = ""
    menu_groups: List[str] = field(default_factory=list)
    button_result: Optional[ButtonExecutionPathResult] = None
    available_to_requester: Optional[bool] = None
    unavailable_reason: str = ""
    summary_text: str = ""
    execution_steps: List[str] = field(default_factory=list)
    evidence: List[Evidence] = field(default_factory=list)


def _menu_breadcrumb(G: nx.DiGraph, menu_node_id: str) -> List[str]:
    """Walk CHILD_OF edges from a menu node up to its root, root->leaf order."""
    chain: List[str] = []
    seen = set()
    current = menu_node_id
    while current and current not in seen and current in G:
        seen.add(current)
        chain.append(G.nodes[current].get("name") or current.replace("menu:", ""))
        parent = None
        for _, v, edge_data in G.out_edges(current, data=True):
            if edge_data.get("edge_type") == "CHILD_OF":
                parent = v
                break
        current = parent
    return list(reversed(chain))


def _menus_opening_model(G: nx.DiGraph, model_name: str):
    """
    Every Menu node with an OPENS_MODEL edge to model_name, most-useful-first:
    menus with no group restriction (broadest real navigation path) sort
    before restricted ones, ties broken by declared menu sequence.
    """
    model_node_id = f"model:{model_name}"
    candidates = []
    if model_node_id not in G:
        return candidates
    for u, _, edge_data in G.in_edges(model_node_id, data=True):
        if edge_data.get("edge_type") == "OPENS_MODEL" and u.startswith("menu:"):
            candidates.append((u, G.nodes[u]))
    candidates.sort(key=lambda c: (bool(c[1].get("groups")), c[1].get("sequence", 999)))
    return candidates


def describe_navigation_path(
    G: nx.DiGraph,
    model_name: str,
    button_label_or_name: str = "",
    user_groups: Optional[List[str]] = None,
) -> NavigationPathResult:
    """
    Answers the statically-derivable subset of "comment faire pour X"
    (Bloc 17, Etage 1): which menu opens the model, and -- when a
    button/action label is supplied -- which button triggers it, calling
    which method, under which group/visibility conditions (delegates to
    button_execution_path for that part, DRY with the existing tool).

    Three possible outcomes, never fabricated:
      - QueryStatus.NOT_FOUND: the model itself is not in the graph.
      - QueryStatus.EMPTY: the model exists but no ir.ui.menu opens it
        (the "aucun chemin UI" verdict from todo/bloc17_jour1_perimetre.md --
        a real and expected outcome for backend-only/fixture modules, not
        a failure to be papered over with an invented menu).
      - QueryStatus.FOUND: a real navigation path, sourced with file link
        and xml_id citation.
    """
    model_node_id = f"model:{model_name}"
    if model_node_id not in G:
        return NavigationPathResult(
            model_name=model_name,
            button_identifier=button_label_or_name,
            status=QueryStatus.NOT_FOUND,
            summary_text=f"Model '{model_name}' {NOT_FOUND_MARKER}.",
        )

    menu_candidates = _menus_opening_model(G, model_name)
    if not menu_candidates:
        summary = (
            f"Aucun chemin d'interface trouvé pour '{model_name}' : le modele existe dans le graphe "
            f"de connaissance, mais aucun menu (ir.ui.menu) ne l'ouvre via une action. Soit ce modele "
            f"n'est exposé que par du code/une automatisation (pas de parcours utilisateur reel), soit "
            f"son menu n'a pas encore été extrait."
        )
        return NavigationPathResult(
            model_name=model_name,
            button_identifier=button_label_or_name,
            status=QueryStatus.EMPTY,
            summary_text=summary,
            execution_steps=[f"1. Menu Search: no ir.ui.menu opens model '{model_name}'."],
            evidence=[make_evidence(
                source_type=EvidenceSourceType.CODE,
                claim=f"Model '{model_name}' exists in the graph but no ir.ui.menu opens it via an action",
                source=model_node_id,
                value=None,
                confidence="HIGH",
            )],
        )

    menu_node_id, menu_data = menu_candidates[0]
    breadcrumb = _menu_breadcrumb(G, menu_node_id)
    menu_xml_id = menu_data.get("xml_id", "")
    menu_groups = sorted(menu_data.get("groups", []))
    menu_fp = menu_data.get("filepath", "")
    menu_link = format_file_link(menu_fp) if menu_fp else ""

    execution_steps = [f"1. UI Menu: navigate to " + " -> ".join(breadcrumb) + f" (id: {menu_xml_id})."]
    if menu_link:
        execution_steps.append(f"2. File Declaration: declared at {menu_link}.")
    if menu_groups:
        citations = format_xml_id_citations(menu_groups)
        execution_steps.append(f"3. Menu Visibility: restricted to groups [{', '.join(menu_groups)}]. ({citations})")
    else:
        execution_steps.append("3. Menu Visibility: no group restriction on the menu itself.")

    evidence = [make_evidence(
        source_type=EvidenceSourceType.CODE,
        claim=f"Menu '{' -> '.join(breadcrumb)}' (id: {menu_xml_id}) opens model '{model_name}'",
        source=menu_node_id,
        value=menu_xml_id,
        confidence="HIGH",
    )]
    if menu_groups:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Menu '{menu_xml_id}' is restricted to groups: {', '.join(menu_groups)}",
            source=menu_node_id,
            value=menu_groups,
            confidence="HIGH",
        ))

    button_result: Optional[ButtonExecutionPathResult] = None
    if button_label_or_name:
        button_result = button_execution_path(G, button_label_or_name, model_name, user_groups=user_groups)
        execution_steps.extend(f"4.{i + 1}. {s}" for i, s in enumerate(button_result.execution_steps))
        evidence.extend(button_result.evidence)

    combined_required_groups = set(menu_groups)
    if button_result:
        combined_required_groups.update(button_result.required_groups)

    available_to_requester: Optional[bool] = None
    unavailable_reason = ""
    if user_groups is not None:
        available_to_requester = _requester_satisfies_required_groups(
            G, sorted(combined_required_groups), user_groups
        )
        if not available_to_requester:
            unavailable_reason = (
                f"Le chemin d'interface vers '{model_name}' n'est pas disponible pour ce demandeur : "
                f"groupes requis [{', '.join(sorted(combined_required_groups))}], dont il ne fait "
                f"partie d'aucun (menu absent et/ou bouton indisponible dans l'interface)."
            )
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(
                f"Navigation path to '{model_name}' is "
                f"{'available' if available_to_requester else 'NOT available'} to this requester"
            ),
            source=menu_node_id,
            value=available_to_requester,
            confidence="HIGH",
            scope={"user_groups": sorted(user_groups)},
        ))

    summary_parts = [f"Pour '{model_name}': menu " + " -> ".join(breadcrumb) + f" (id: {menu_xml_id})."]
    if menu_groups:
        summary_parts.append(f"Menu restreint aux groupes [{', '.join(menu_groups)}].")
    if button_result:
        summary_parts.append(button_result.summary_text)
    if unavailable_reason:
        summary_parts.append(f"NON DISPONIBLE POUR LE DEMANDEUR : {unavailable_reason}")

    return NavigationPathResult(
        model_name=model_name,
        button_identifier=button_label_or_name,
        status=QueryStatus.FOUND,
        menu_breadcrumb=breadcrumb,
        menu_xml_id=menu_xml_id,
        menu_groups=menu_groups,
        button_result=button_result,
        available_to_requester=available_to_requester,
        unavailable_reason=unavailable_reason,
        summary_text=" ".join(summary_parts),
        execution_steps=execution_steps,
        evidence=evidence,
    )
