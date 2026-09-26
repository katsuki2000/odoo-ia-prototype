"""
code_intelligence/deterministic/menu_view_finder.py

Dynamic view injection (get_view / fields_view_get) and UI Menu item
lookup for actions not found in static button declarations.
"""

from pathlib import Path
import re
from typing import Optional
import networkx as nx

from code_intelligence.rules.button_path import ButtonExecutionPathResult
from code_intelligence.rules.group_resolver import get_group_display_name
from code_intelligence.utils import format_file_link, format_xml_id_citations


def search_dynamic_view_or_menus(
    G: nx.DiGraph,
    model_name: str,
    button_label_or_name: str,
) -> Optional[ButtonExecutionPathResult]:
    """
    Checks if dynamic view injection (get_view / fields_view_get) overrides exist on this model,
    or searches Menu nodes matching the requested label/name.
    """
    get_view_id = f"method:{model_name}.get_view"
    fvg_id = f"method:{model_name}.fields_view_get"
    view_hook_id = get_view_id if get_view_id in G else (fvg_id if fvg_id in G else None)
    if view_hook_id:
        hook_data = G.nodes[view_hook_id]
        hook_name = hook_data.get("name", "get_view")
        hook_fp = hook_data.get("filepath", "")
        hook_line = hook_data.get("lineno", 0)
        hook_sites = hook_data.get("override_sites") or []
        end_line = hook_sites[0].get("end_lineno", hook_line + 48) if hook_sites else (hook_line + 48)
        hook_file_link = format_file_link(hook_fp, hook_line, end_line)
        dynamic_summary = (
            f"Button '{button_label_or_name}' on '{model_name}': No static XML button declaration found in views. "
            f"Dynamic View Injection Detected: Method '{model_name}.{hook_name}' is overridden at {hook_file_link}. "
            f"In Odoo, models overriding {hook_name}() dynamically inject buttons, labels, and widgets into the view arch "
            f"at runtime (via xpath on /form/header/button, QWeb rendering, or _tier_validation_manual_config) "
            f"without declaring them in static XML view files."
        )
        return ButtonExecutionPathResult(
            button_identifier=button_label_or_name,
            model_name=model_name,
            method_name=hook_name,
            origin_states=[],
            target_state="",
            required_groups=[],
            execution_steps=[
                f"1. Dynamic View Injection: Method '{model_name}.{hook_name}()' dynamically processes form view XML.",
                f"2. Source Hook: Defined at {hook_file_link}.",
                f"3. Runtime XPath: Injects dynamic buttons into form header at runtime without static XML view declaration.",
            ],
            summary_text=dynamic_summary,
            evidence=[],
            method_filepath=hook_fp,
            method_lineno=hook_line,
            method_end_lineno=end_line,
        )

    target_modules = set()
    model_node = f"model:{model_name}"
    if model_node in G:
        for neighbor in G.neighbors(model_node):
            edge_data = G.get_edge_data(model_node, neighbor) or {}
            if edge_data.get("edge_type") == "DEFINED_IN":
                target_modules.add(neighbor.replace("module:", ""))
    if not target_modules:
        target_modules.add(model_name.split(".")[0])

    btn_clean = button_label_or_name.strip().lower()
    scored_menus = []
    for node_id, data in G.nodes(data=True):
        if data.get("node_type") == "Menu":
            m_name = (data.get("name") or "").strip()
            m_xml_id = (data.get("xml_id") or "").strip()
            m_mod = m_xml_id.split(".")[0] if "." in m_xml_id else ""
            name_match = (btn_clean == m_name.lower()) or (len(btn_clean) >= 3 and btn_clean in m_name.lower())
            id_match = (btn_clean == m_xml_id.lower()) or (len(btn_clean) >= 3 and btn_clean in m_xml_id.lower())
            if not (name_match or id_match):
                continue
            score = 0
            if m_mod in target_modules:
                score += 10
            if btn_clean == m_name.lower():
                score += 5
            if btn_clean == m_xml_id.lower():
                score += 3
            scored_menus.append((score, node_id, data))

    if scored_menus:
        scored_menus.sort(key=lambda x: x[0], reverse=True)
        _score, menu_id, menu_data = scored_menus[0]
        menu_name = menu_data.get("name", button_label_or_name)
        menu_xml_id = menu_data.get("xml_id", "")
        menu_fp = menu_data.get("filepath", "")
        menu_groups = menu_data.get("groups", [])
        formatted_menu_groups = [
            f"{g} ('{get_group_display_name(G, g)}')" if get_group_display_name(G, g) else g
            for g in sorted(menu_groups)
        ]
        grp_str = ", ".join(formatted_menu_groups) if menu_groups else "None"
        req_citations = format_xml_id_citations(sorted(menu_groups)) if menu_groups else ""
        citations_str = f" ({req_citations})" if req_citations else ""

        menu_lineno = 1
        end_lineno = 10
        if menu_fp:
            p = Path(menu_fp)
            if p.exists():
                try:
                    m_txt = p.read_text(encoding="utf-8")
                    rec_id = menu_xml_id.split(".")[-1]
                    m_pos = re.search(r"id=[\"']" + re.escape(rec_id) + r"[\"']", m_txt)
                    if m_pos:
                        menu_lineno = m_txt[:m_pos.start()].count("\n") + 1
                        after = m_txt[m_pos.start():]
                        close_tag = after.find("</record>")
                        if close_tag != -1:
                            end_lineno = menu_lineno + after[:close_tag].count("\n")
                        else:
                            end_lineno = menu_lineno + 6
                except Exception:
                    pass
        menu_link = f"[{Path(menu_fp).name}:L{menu_lineno}-L{end_lineno}](file://{menu_fp}#L{menu_lineno}-L{end_lineno})" if menu_fp else menu_fp

        menu_steps = [
            f"1. UI Menu: User navigates to menu item '{menu_name}' (id: {menu_xml_id}).",
            f"2. File Declaration: Declared in {menu_link}.",
            f"3. Security Requirement: Menu restricted to groups [{grp_str}].{citations_str}",
        ]
        menu_summary = (
            f"Menu '{menu_name}' (id: {menu_xml_id}) in {menu_link}: "
            f"Restricted to groups [{grp_str}].{citations_str} "
            f"Only users belonging to these groups have visibility to this menu item."
        )
        return ButtonExecutionPathResult(
            button_identifier=button_label_or_name,
            model_name=model_name,
            method_name="",
            origin_states=[],
            target_state="",
            required_groups=sorted(menu_groups),
            execution_steps=menu_steps,
            summary_text=menu_summary,
            evidence=[],
            method_filepath=menu_fp,
            method_lineno=menu_lineno,
            method_end_lineno=end_lineno,
        )

    return None

# ── Navigation Path ──────────────────────────────────────────────────────

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

from code_intelligence.rules.common import NOT_FOUND_MARKER, QueryStatus
from code_intelligence.utils import format_file_link, format_xml_id_citations
from core.evidence.evidence import Evidence, EvidenceSourceType, make_evidence


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
    # Deferred import: button_path imports search_dynamic_view_or_menus from
    # this module at module load time, so importing these names back at the
    # top of this file would create a circular import.
    from code_intelligence.rules.button_path import (
        _requester_satisfies_required_groups,
        button_execution_path,
    )

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
        formatted_menu_groups = [
            f"{g} ('{get_group_display_name(G, g)}')" if get_group_display_name(G, g) else g
            for g in sorted(menu_groups)
        ]
        citations = format_xml_id_citations(menu_groups)
        execution_steps.append(f"3. Menu Visibility: restricted to groups [{', '.join(formatted_menu_groups)}]. ({citations})")
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
        formatted_menu_groups = [
            f"{g} ('{get_group_display_name(G, g)}')" if get_group_display_name(G, g) else g
            for g in sorted(menu_groups)
        ]
        summary_parts.append(f"Menu restreint aux groupes [{', '.join(formatted_menu_groups)}].")
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
