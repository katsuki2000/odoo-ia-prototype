"""
code_intelligence/deterministic/menu_view_finder.py

Dynamic view injection (get_view / fields_view_get) and UI Menu item
lookup for actions not found in static button declarations.
"""

import logging
from pathlib import Path
import re
from typing import Optional
import networkx as nx

from code_intelligence.rules.button_path import ButtonExecutionPathResult
from code_intelligence.rules.group_resolver import format_groups
from code_intelligence.utils import format_file_link, format_xml_id_citations

_logger = logging.getLogger(__name__)


ORPHAN_ACTION_MARKER = "elle n'est rattachee a aucun menu"
MAX_CLIENT_ACTION_MENUS = 5
MAX_LISTED_FIELDS = 25
MAX_LISTED_BUTTONS = 15

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
            f"Button '{button_label_or_name}' on '{model_name}' was not found in static XML button declarations. "
            f"An override of '{model_name}.{hook_name}' exists at {hook_file_link}, but the override's body "
            "has not been verified to inject this button. Its existence alone is not evidence that the requested "
            "button is added dynamically."
        )
        return ButtonExecutionPathResult(
            button_identifier=button_label_or_name,
            model_name=model_name,
            method_name=hook_name,
            origin_states=[],
            target_state="",
            required_groups=[],
            execution_steps=[
                f"1. Static XML Search: No matching button declaration was found.",
                f"2. View Hook: Override '{model_name}.{hook_name}()' exists at {hook_file_link}.",
                "3. Unresolved: The hook body has not been verified to inject the requested button.",
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
        formatted_menu_groups = format_groups(G, menu_groups)
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
                except (OSError, UnicodeDecodeError) as err:
                    _logger.warning("Cannot read menu file %s: %s", menu_fp, err)
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
from typing import Any, List, Optional
import networkx as nx

from code_intelligence.agent.node_labels import node_labels
from code_intelligence.rules.common import QueryStatus
from code_intelligence.rules.model_suggestions import model_not_found_message
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
    # (menu xml_id, groups) for every menu of the CHILD_OF chain
    # that carries groups. Odoo needs one group of EACH entry (OR inside a
    # menu, AND between menus).
    menu_group_requirements: List[Any] = field(default_factory=list)
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
        chain.append(" / ".join(node_labels(G.nodes[current])) or current.replace("menu:", ""))
        parent = None
        for _, v, edge_data in G.out_edges(current, data=True):
            if edge_data.get("edge_type") == "CHILD_OF":
                parent = v
                break
        current = parent
    return list(reversed(chain))


def _menu_chain_group_requirements(G: nx.DiGraph, menu_node_id: str):
    """walk CHILD_OF edges leaf -> root and return
    ([(menu xml_id, sorted groups)] for menus carrying groups, chain length)."""
    requirements = []
    seen = set()
    current = menu_node_id
    while current and current not in seen and current in G:
        seen.add(current)
        data = G.nodes[current]
        groups = sorted(data.get("groups", []) or [])
        if groups:
            requirements.append((data.get("xml_id") or current.replace("menu:", ""), groups))
        parent = None
        for _, v, edge_data in G.out_edges(current, data=True):
            if edge_data.get("edge_type") == "CHILD_OF":
                parent = v
                break
        current = parent
    return requirements, len(seen)


def _menus_opening_model(G: nx.DiGraph, model_name: str, origin_states: Optional[List[str]] = None):
    """
    Every Menu node with an OPENS_MODEL edge to model_name, most-useful-first:
    menus whose action domain admits at least one origin state of the button
    come first (all of them when none does or the states are unknown), then
    menus with no group restriction (broadest real navigation path), ties
    broken by declared menu sequence.
    """
    from code_intelligence.graph.workflow_extraction import domain_admits_any_state

    model_node_id = f"model:{model_name}"
    candidates = []
    if model_node_id not in G:
        return candidates
    state_field = G.nodes[model_node_id].get("state_field")
    for u, _, edge_data in G.in_edges(model_node_id, data=True):
        if edge_data.get("edge_type") == "OPENS_MODEL" and u.startswith("menu:"):
            candidates.append((u, G.nodes[u]))
    compatible = [
        c for c in candidates
        if domain_admits_any_state(c[1].get("action_domain", ""), origin_states or [], state_field)
    ]
    candidates = compatible or candidates
    candidates.sort(key=lambda c: (bool(c[1].get("groups")), c[1].get("sequence", 999)))
    return candidates


def _client_action_menus(G: nx.DiGraph, model_name: str):
    """Menus of the modules declaring model_name that open a client action, most-useful-first."""
    modules = {
        v.removeprefix("module:")
        for _, v, edge_data in G.out_edges(f"model:{model_name}", data=True)
        if edge_data.get("edge_type") == "DEFINED_IN" and edge_data.get("role", "declares") == "declares"
    }
    candidates = [
        (node_id, data) for node_id, data in G.nodes(data=True)
        if data.get("node_type") == "Menu" and data.get("action_type") == "client" and data.get("module") in modules
    ]
    candidates.sort(key=lambda c: (bool(c[1].get("groups")), c[1].get("sequence", 999), c[0]))
    return candidates[:MAX_CLIENT_ACTION_MENUS]


def _field_display_label(data) -> str:
    labels = node_labels(data)
    if data.get("label_source") == "generated" and len(labels) > 1:
        labels = labels[1:]
    return " / ".join(labels)


def _form_overview(G: nx.DiGraph, model_name: str):
    """Fields of the model and buttons indexed in its XML views, so a "how do I" answer is not written from memory."""
    fields: List[str] = []
    buttons: List[str] = []
    for _, target, edge_data in G.out_edges(f"model:{model_name}", data=True):
        data = G.nodes.get(target, {})
        if edge_data.get("edge_type") == "HAS_FIELD" and data.get("node_type") == "Field":
            fields.append(f"{_field_display_label(data)} ({data.get('field_type', '')})")
        elif edge_data.get("edge_type") == "HAS_BUTTON" and data.get("node_type") == "Button":
            buttons.append(str(data.get("label") or data.get("name") or "").strip())
    buttons = list(dict.fromkeys(label for label in buttons if label))
    if not fields:
        return "", []
    parts: List[str] = []
    evidence: List[Evidence] = []
    if len(fields) <= MAX_LISTED_FIELDS:
        parts.append(f"Champs du modele '{model_name}' ({len(fields)}) : {', '.join(fields)}.")
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Model '{model_name}' has the fields: {', '.join(fields)}",
            source=f"fields:{model_name}",
            value=len(fields),
            confidence="HIGH",
        ))
    else:
        parts.append(f"Le modele '{model_name}' a {len(fields)} champs (liste omise).")
    if not buttons:
        parts.append("Aucun bouton n'est declare dans les vues XML indexees de ce modele.")
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"No button is declared in the indexed XML views of model '{model_name}'",
            source=f"buttons:{model_name}",
            value=0,
            confidence="MEDIUM",
        ))
    elif len(buttons) <= MAX_LISTED_BUTTONS:
        parts.append(f"Boutons declares dans les vues XML indexees : {', '.join(buttons)}.")
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Model '{model_name}' has the buttons declared in its indexed XML views: {', '.join(buttons)}",
            source=f"buttons:{model_name}",
            value=len(buttons),
            confidence="HIGH",
        ))
    else:
        parts.append(f"{len(buttons)} boutons declares dans les vues XML indexees (liste omise).")
    parts.append(
        "Un champ liste n'est pas forcement affiche dans la vue, et l'absence de bouton ne couvre pas un bouton "
        "ajoute dynamiquement ou par une vue non indexee."
    )
    return " ".join(parts), evidence


def describe_navigation_path(
    G: nx.DiGraph,
    model_name: str,
    button_label_or_name: str = "",
    user_groups: Optional[List[str]] = None,
) -> NavigationPathResult:
    """
    Answers the statically-derivable subset of "comment faire pour X":
    which menu opens the model, and -- when a
    button/action label is supplied -- which button triggers it, calling
    which method, under which group/visibility conditions (delegates to
    button_execution_path for that part, DRY with the existing tool).

    Three possible outcomes, never fabricated:
      - QueryStatus.NOT_FOUND: the model itself is not in the graph.
      - QueryStatus.EMPTY: the model exists but no ir.ui.menu opens it
        (the "aucun chemin UI" verdict --
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
            summary_text=model_not_found_message(G, model_name),
        )

    button_result: Optional[ButtonExecutionPathResult] = None
    if button_label_or_name:
        button_result = button_execution_path(G, button_label_or_name, model_name, user_groups=user_groups)

    overview, overviewEvidence = _form_overview(G, model_name)
    menu_candidates = _menus_opening_model(G, model_name, button_result.origin_states if button_result else None)
    if not menu_candidates:
        window_actions = G.nodes[model_node_id].get("window_actions") or []
        if window_actions:
            action_labels = ", ".join(
                f"'{a['name']}' ({a['xml_id']})" if a.get("name") else a["xml_id"]
                for a in window_actions
            )
            summary = (
                f"Aucun menu (ir.ui.menu) n'ouvre '{model_name}'. Une action fenetre le cible pourtant : "
                f"{action_labels}, mais {ORPHAN_ACTION_MARKER} : le parcours utilisateur "
                f"normal n'existe pas dans le code analyse."
            )
            steps = [
                f"1. Menu Search: no ir.ui.menu opens model '{model_name}'.",
                f"2. Window action(s) targeting the model without a menu: {action_labels}.",
            ]
            claim = (
                f"Model '{model_name}' has window action(s) {action_labels} but no ir.ui.menu opens it"
            )
        else:
            summary = (
                f"Aucun chemin d'interface trouvé pour '{model_name}' : le modele existe dans le graphe "
                f"de connaissance, mais ni menu (ir.ui.menu) ni action fenetre ne l'ouvre. Soit ce modele "
                f"n'est exposé que par du code/une automatisation (pas de parcours utilisateur reel), soit "
                f"son menu n'a pas encore été extrait."
            )
            steps = [f"1. Menu Search: no ir.ui.menu opens model '{model_name}'."]
            claim = f"Model '{model_name}' exists in the graph but no ir.ui.menu opens it via an action"
        evidence = [make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=claim,
            source=model_node_id,
            value=None,
            confidence="HIGH",
        )]
        clientMenus = _client_action_menus(G, model_name)
        if clientMenus:
            entries = "; ".join(
                f"{' -> '.join(_menu_breadcrumb(G, node_id))} (id: {data.get('xml_id', '')}, "
                f"action client '{data.get('action_tag') or data.get('action_ref', '')}')"
                for node_id, data in clientMenus
            )
            summary += (
                f" Le module qui declare '{model_name}' expose cependant un menu qui ouvre une action client "
                f"(ecran JavaScript, sans modele enregistre) : {entries}. Le code analyse ne prouve pas que "
                f"cet ecran affiche '{model_name}'."
            )
            steps.append(f"{len(steps) + 1}. Client action menu(s) in the declaring module: {entries}.")
            evidence.extend(make_evidence(
                source_type=EvidenceSourceType.CODE,
                claim=f"Menu '{data.get('xml_id', '')}' opens client action '{data.get('action_ref', '')}' "
                      f"in a module declaring '{model_name}'",
                source=node_id,
                value=data.get("xml_id", ""),
                confidence="MEDIUM",
            ) for node_id, data in clientMenus)
        if overview:
            summary += " " + overview
            steps.append(f"{len(steps) + 1}. Form overview: {overview}")
            evidence.extend(overviewEvidence)
        return NavigationPathResult(
            model_name=model_name,
            button_identifier=button_label_or_name,
            status=QueryStatus.EMPTY,
            summary_text=summary.strip(),
            execution_steps=steps,
            evidence=evidence,
        )

    menu_node_id, menu_data = menu_candidates[0]
    breadcrumb = _menu_breadcrumb(G, menu_node_id)
    menu_xml_id = menu_data.get("xml_id", "")
    menu_requirements, chain_length = _menu_chain_group_requirements(G, menu_node_id)
    menu_groups = sorted({g for _, groups in menu_requirements for g in groups})
    menu_fp = menu_data.get("filepath", "")
    menu_link = format_file_link(menu_fp) if menu_fp else ""

    execution_steps = [f"1. UI Menu: navigate to " + " -> ".join(breadcrumb) + f" (id: {menu_xml_id})."]
    if menu_link:
        execution_steps.append(f"2. File Declaration: declared at {menu_link}.")
    if len(menu_requirements) == 1 and chain_length == 1:
        citations = format_xml_id_citations(menu_groups)
        execution_steps.append(
            f"3. Menu Visibility: restricted to groups [{', '.join(format_groups(G, menu_groups))}]. ({citations})"
        )
    elif menu_requirements:
        per_menu = "; ".join(
            f"menu {xml_id} requires one of [{', '.join(format_groups(G, groups))}]"
            for xml_id, groups in menu_requirements
        )
        citations = format_xml_id_citations(menu_groups)
        execution_steps.append(
            f"3. Menu Visibility: the user needs one group for EACH restricted menu of the path: "
            f"{per_menu}. ({citations})"
        )
    elif chain_length > 1:
        execution_steps.append("3. Menu Visibility: no group restriction on the menu or its parent menus.")
    else:
        execution_steps.append("3. Menu Visibility: no group restriction on the menu itself.")

    evidence = [make_evidence(
        source_type=EvidenceSourceType.CODE,
        claim=f"Menu '{' -> '.join(breadcrumb)}' (id: {menu_xml_id}) opens model '{model_name}'",
        source=menu_node_id,
        value=menu_xml_id,
        confidence="HIGH",
    )]
    for restricted_xml_id, restricted_groups in menu_requirements:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Menu '{restricted_xml_id}' is restricted to groups: {', '.join(restricted_groups)}",
            source=f"menu:{restricted_xml_id}",
            value=restricted_groups,
            confidence="HIGH",
        ))

    if button_result:
        execution_steps.extend(f"4.{i + 1}. {s}" for i, s in enumerate(button_result.execution_steps))
        evidence.extend(button_result.evidence)
    if overview:
        execution_steps.append(f"5. Form overview: {overview}")
        evidence.extend(overviewEvidence)

    combined_required_groups = set(menu_groups)
    if button_result:
        combined_required_groups.update(button_result.required_groups)

    # one group of EACH restricted menu of the chain, AND one
    # group of the button when it has any (previously a single OR over the union).
    requirement_sets = [list(groups) for _, groups in menu_requirements]
    if button_result and button_result.required_groups:
        requirement_sets.append(sorted(button_result.required_groups))

    available_to_requester: Optional[bool] = None
    unavailable_reason = ""
    if user_groups is not None:
        unsatisfied_sets = [
            group_set for group_set in requirement_sets
            if not _requester_satisfies_required_groups(G, group_set, user_groups)
        ]
        available_to_requester = not unsatisfied_sets
        if not available_to_requester:
            unavailable_reason = (
                f"Le chemin d'interface vers '{model_name}' n'est pas disponible pour ce demandeur : "
                f"il lui faut un groupe parmi chacun de ces ensembles "
                f"{' ET '.join('[' + ', '.join(gs) + ']' for gs in unsatisfied_sets)}, dont il ne fait "
                f"partie d'aucun pour au moins l'un d'eux (menu absent et/ou bouton indisponible dans l'interface)."
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
    if len(menu_requirements) == 1 and chain_length == 1:
        summary_parts.append(f"Menu restreint aux groupes [{', '.join(format_groups(G, menu_groups))}].")
    elif menu_requirements:
        summary_parts.append(
            "Menus restreints (un groupe de chacun est requis) : "
            + " ; ".join(
                f"{xml_id} [{', '.join(format_groups(G, groups))}]"
                for xml_id, groups in menu_requirements
            ) + "."
        )
    if button_result:
        summary_parts.append(button_result.summary_text)
    if overview:
        summary_parts.append(overview)
    if unavailable_reason:
        summary_parts.append(f"NON DISPONIBLE POUR LE DEMANDEUR : {unavailable_reason}")

    return NavigationPathResult(
        model_name=model_name,
        button_identifier=button_label_or_name,
        status=QueryStatus.FOUND,
        menu_breadcrumb=breadcrumb,
        menu_xml_id=menu_xml_id,
        menu_groups=menu_groups,
        menu_group_requirements=menu_requirements,
        button_result=button_result,
        available_to_requester=available_to_requester,
        unavailable_reason=unavailable_reason,
        summary_text=" ".join(summary_parts),
        execution_steps=execution_steps,
        evidence=evidence,
    )
