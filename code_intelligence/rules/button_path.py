"""
code_intelligence/deterministic/button_path_models.py

Data structures and evidence generation for Odoo button execution paths and UI field inspection.
"""

from dataclasses import dataclass, field
import re
from typing import List, Optional, Set

from core.evidence.evidence import Evidence, EvidenceSourceType, make_evidence


def correct_button_role_contradictions(final_answer: str, raw_tool_output: str) -> str:
    """Clarify manager claims that contradict a button's required group."""
    pattern = re.compile(
        r"Button\s+'[^']+'[^\n]*Calls\s+'([A-Za-z_][A-Za-z0-9_]*)\(\)'[^\n]*"
        r"Required Groups:\s*\[([^\]]*)\]",
        re.IGNORECASE,
    )
    corrected = final_answer
    for method_name, required_groups in pattern.findall(raw_tool_output):
        if method_name not in corrected or "manager" not in corrected.lower():
            continue
        if "manager" in required_groups.lower():
            continue
        for block in re.split(r"\n\s*\n", corrected):
            if method_name not in block or "manager" not in block.lower():
                continue
            clarification = (
                f"Précision déterministe : le chemin de `button_execution_path` pour "
                f"`{method_name}()` indique les groupes requis "
                f"`{required_groups.strip() or 'aucun'}` ; il ne permet pas d'attribuer "
                "cette action au groupe manager sans preuve supplémentaire."
            )
            lines = block.splitlines()
            replaced = False
            for index, line in enumerate(lines):
                if method_name in line and "manager" in line.lower():
                    prefix = "- " if line.lstrip().startswith(("-", "*")) else ""
                    lines[index] = prefix + clarification
                    replaced = True
            replacement = "\n".join(lines)
            if replaced:
                has_markdown_heading = any(
                    re.match(r"^\s*(?:#+\s|\d+\.\s+\*\*)", line)
                    for line in lines
                )
                substantive_lines = [
                    line for line in lines
                    if line.strip()
                    and not re.match(r"^\s*(?:\d+\.\s+)?#+\s|^\s*\d+\.\s+\*\*", line)
                    and "Précision déterministe" not in line
                ]
                corrected = corrected.replace(
                    block,
                    "" if has_markdown_heading and not substantive_lines else replacement,
                    1,
                )
                corrected = re.sub(r"\n{3,}", "\n\n", corrected).strip()
    return corrected


def correct_button_visibility_contradictions(final_answer: str, raw_tool_output: str) -> str:
    """Correct an inverted interpretation of a button's invisible expression."""
    match = re.search(
        r"Visibility:\s*invisible\s*=\s*['\"]?\s*([\w.]+)\s*!=\s*['\"]([^'\"]+)['\"]",
        raw_tool_output,
        re.IGNORECASE,
    )
    if not match or not re.search(r"invers|erron", final_answer, re.IGNORECASE):
        return final_answer
    field_name, visible_state = match.groups()
    blocks = re.split(r"\n\s*\n", final_answer)
    blocks = [
        block for block in blocks
        if not re.search(
            r"^\s*\d+\.\s+\*\*Condition de visibilité (?:inversée|erronée)\*\*",
            block,
            re.IGNORECASE,
        )
    ]
    corrected = "\n\n".join(blocks).rstrip()
    fact = (
        f"[FAIT DÉTERMINISTIQUE -- VISIBILITÉ DU BOUTON] La condition `invisible` "
        f"est `{field_name} != '{visible_state}'` : le bouton est donc visible "
        f"lorsque `{field_name} == '{visible_state}'`, sous réserve de ses groupes requis."
    )
    return corrected + "\n\n" + fact


@dataclass
class ButtonExecutionPathResult:
    button_identifier: str
    model_name: str
    method_name: str = ""
    origin_states: List[str] = field(default_factory=list)
    target_state: str = ""
    required_groups: List[str] = field(default_factory=list)
    execution_steps: List[str] = field(default_factory=list)
    summary_text: str = ""
    # Whether the button is available to the requester
    available_to_requester: Optional[bool] = None
    unavailable_reason: str = ""
    # Bloc P2 Jour 4: called method's own behavioral_tags/technical_tags
    method_tags: List[str] = field(default_factory=list)
    # B1 replication of the B0 pilot: structured Evidence produced at the source.
    evidence: List[Evidence] = field(default_factory=list)
    # todo/contexte.txt section 831 (Famille 1, site 5/5): filepath/lineno/
    # end_lineno of the called method's own definition, already computed
    # locally to build method_link_str below -- exposed here so callers do
    # not need to re-parse the file:// link out of summary_text.
    method_filepath: str = ""
    method_lineno: int = 0
    method_end_lineno: int = 0


def _build_button_execution_evidence(
    button_label_or_name: str,
    model_name: str,
    method_name: str,
    method_exists: bool,
    origin_states: Set[str],
    target_state: str,
    required_groups: Set[str],
    user_groups: Optional[List[str]],
    available_to_requester: Optional[bool],
) -> List[Evidence]:
    """
    B1: four structural facts, each always asserted explicitly.
    """
    evidence: List[Evidence] = []

    evidence.append(make_evidence(
        source_type=EvidenceSourceType.CODE,
        claim=(
            f"Button '{button_label_or_name}' on '{model_name}' calls method "
            f"'{method_name}()' (method_exists={method_exists})"
        ),
        source=f"method:{model_name}.{method_name}",
        value=method_name,
        confidence="HIGH",
    ))

    if origin_states and target_state:
        origins_str = ", ".join(sorted(origin_states))
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(
                f"Button '{button_label_or_name}' transitions '{model_name}' "
                f"from [{origins_str}] to '{target_state}'"
            ),
            source=f"transition:{model_name}:{method_name}",
            value=target_state,
            confidence="HIGH",
        ))
    else:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Button '{button_label_or_name}' on '{model_name}' triggers no workflow state transition",
            source=f"transition:{model_name}:{method_name}",
            value=None,
            confidence="HIGH",
        ))

    if required_groups:
        grp_str = ", ".join(sorted(required_groups))
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Button '{button_label_or_name}' on '{model_name}' is restricted to groups: {grp_str}",
            source=f"button_security:{model_name}:{method_name}",
            value=sorted(required_groups),
            confidence="HIGH",
        ))
    else:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Button '{button_label_or_name}' on '{model_name}' carries no button-level group restriction",
            source=f"button_security:{model_name}:{method_name}",
            value=None,
            confidence="HIGH",
        ))

    if user_groups is not None:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(
                f"Button '{button_label_or_name}' on '{model_name}' is "
                f"{'available' if available_to_requester else 'NOT available'} to this requester"
            ),
            source=f"button_availability:{model_name}:{method_name}",
            value=available_to_requester,
            confidence="HIGH",
            scope={"user_groups": sorted(user_groups)},
        ))

    return evidence

# ── Button Path ──────────────────────────────────────────────────────────

"""
code_intelligence/deterministic/button_path.py

Tracing execution paths for Odoo UI buttons, menu items, and workflow transitions.
"""

from typing import List, Optional, Set
import networkx as nx

from code_intelligence.rules.common import NOT_FOUND_MARKER
from code_intelligence.rules.group_resolver import (
    _expand_implied_user_groups,
    get_group_display_name,
    resolve_group_identifier,
)
from code_intelligence.rules.navigation import search_dynamic_view_or_menus
from code_intelligence.rules.technical_groups import technical_groups_among
from code_intelligence.rules.xml_view_finder import _find_field_in_xml_views
from code_intelligence.rules.ontology import tags_for_node_attrs
from code_intelligence.utils import format_file_link, format_xml_id_citations


def _requester_satisfies_required_groups(
    G: nx.DiGraph, required_groups: List[str], user_groups: List[str]
) -> bool:
    """
    True if the demandeur belongs to at least one of required_groups (Odoo
    button-level groups="..." is an OR condition across the listed groups).
    """
    if not required_groups:
        return True
    if not user_groups:
        return False

    user_group_set: Set[str] = set(user_groups)
    for g in list(user_group_set):
        _expand_implied_user_groups(G, g, user_group_set)

    return any(
        resolve_group_identifier(G, ug, required_groups) is not None
        for ug in user_group_set
    )


def button_execution_path(
    G: nx.DiGraph,
    button_label_or_name: str,
    model_name: str,
    user_groups: Optional[List[str]] = None,
) -> ButtonExecutionPathResult:
    """
    Traces step-by-step workflow execution path for a UI button click or UI field inspection.
    Combines UI View Button/Field -> Python Method -> Workflow State Transition -> Security Rules.
    """
    model_node = f"model:{model_name}"

    if model_node not in G:
        return ButtonExecutionPathResult(
            button_identifier=button_label_or_name,
            model_name=model_name,
            summary_text=f"Model '{model_name}' {NOT_FOUND_MARKER}."
        )

    method_name = ""
    origin_states: Set[str] = set()
    target_state = ""
    required_groups: Set[str] = set()
    execution_steps: List[str] = []

    candidate_transitions = []
    target_clean = button_label_or_name.strip().lower()
    for u, v, edge_data in G.edges(data=True):
        if edge_data.get("edge_type") == "TRANSITIONS_VIA":
            state_val = u.replace("state:", "")
            if "." in state_val:
                edge_model = state_val.rsplit(".", 1)[0]
                if edge_model != model_name:
                    continue

            m_name = (edge_data.get("method_name") or "").strip()
            btn_label = (edge_data.get("label_bouton") or "").strip()
            m_lower = m_name.lower()
            lbl_lower = btn_label.lower()

            score = 0
            if target_clean == m_lower or (lbl_lower and target_clean == lbl_lower):
                score = 3
            elif (lbl_lower and target_clean in lbl_lower) or (m_lower and target_clean in m_lower):
                score = 2
            elif (m_lower and m_lower in target_clean) or (lbl_lower and lbl_lower in target_clean):
                score = 1

            if score > 0:
                candidate_transitions.append((score, m_name, u, v, edge_data))

    if candidate_transitions:
        max_score = max(c[0] for c in candidate_transitions)
        best_candidates = [c for c in candidate_transitions if c[0] == max_score]
        chosen_method = best_candidates[0][1]
        for score, m_name, u, v, edge_data in best_candidates:
            if m_name == chosen_method:
                method_name = m_name
                orig_st = u.replace(f"state:{model_name}.", "").replace("state:", "")
                targ_st = v.replace(f"state:{model_name}.", "").replace("state:", "")
                origin_states.add(orig_st)
                target_state = targ_st
                groups_req = edge_data.get("groupe_requis", [])
                if isinstance(groups_req, list):
                    required_groups.update(groups_req)

    invisible_condition = ""
    if not method_name:
        model_node_id = f"model:{model_name}"
        if model_node_id in G:
            candidate_buttons = []
            for _, _, edge_data in G.out_edges(model_node_id, data=True):
                if edge_data.get("edge_type") == "HAS_BUTTON":
                    m_name = (edge_data.get("method_name") or "").strip()
                    btn_label = (edge_data.get("label_bouton") or "").strip()
                    m_lower = m_name.lower()
                    lbl_lower = btn_label.lower()
                    score = 0
                    if target_clean == m_lower or (lbl_lower and target_clean == lbl_lower):
                        score = 3
                    elif (lbl_lower and target_clean in lbl_lower) or (m_lower and target_clean in m_lower):
                        score = 2
                    elif (m_lower and m_lower in target_clean) or (lbl_lower and lbl_lower in target_clean):
                        score = 1
                    if score > 0:
                        candidate_buttons.append((score, m_name, edge_data))
            if candidate_buttons:
                candidate_buttons.sort(key=lambda x: x[0], reverse=True)
                _, method_name, edge_data = candidate_buttons[0]
                groups_req = edge_data.get("groupe_requis", [])
                if isinstance(groups_req, list):
                    required_groups.update(groups_req)
                invisible_condition = edge_data.get("invisible", "")

    if not method_name:
        field_view_res = _find_field_in_xml_views(G, model_name, button_label_or_name, user_groups=user_groups)
        if field_view_res is not None:
            return field_view_res

    if not method_name:
        method_name = button_label_or_name if button_label_or_name.startswith("action_") or button_label_or_name.startswith("_") else f"action_{button_label_or_name.lower()}"

    method_node_id = f"method:{model_name}.{method_name}"
    method_exists = method_node_id in G
    method_tags = tags_for_node_attrs(G.nodes[method_node_id]) if method_exists else []
    method_filepath = ""
    method_lineno = 0
    method_end_lineno = 0

    if not method_exists and not origin_states and not invisible_condition:
        dyn_or_menu = search_dynamic_view_or_menus(G, model_name, button_label_or_name)
        if dyn_or_menu is not None:
            return dyn_or_menu

    if not method_exists and not origin_states and not invisible_condition:
        execution_steps.append(f"1. UI Search: Button or UI element '{button_label_or_name}' was not found in XML views for '{model_name}'.")
        execution_steps.append(f"2. Method Lookup: Candidate method '{method_name}()' is not defined on model '{model_name}'.")
        execution_steps.append("3. State Transition: None.")
        execution_steps.append("4. Security Requirement: None.")
        summary = (
            f"Button or UI element '{button_label_or_name}' on '{model_name}': "
            f"Neither button declaration nor method '{method_name}()' found in knowledge graph. "
            f"Transition: [] -> ''. "
            f"Required Groups: [None]."
        )
    else:
        method_link_str = f"Defined: {method_exists}"
        if method_exists and method_node_id in G:
            m_node = G.nodes[method_node_id]
            m_sites = m_node.get("override_sites") or []
            if m_sites:
                base_site = m_sites[0]
                m_fp = base_site.get("filepath", "")
                m_line = base_site.get("lineno", 0)
                m_end = base_site.get("end_lineno", m_line + 30)
            else:
                m_fp = m_node.get("filepath", "")
                m_line = m_node.get("lineno", 0)
                m_end = m_node.get("end_lineno", m_line + 30)
            if m_fp:
                m_link = format_file_link(m_fp, m_line, m_end)
                method_link_str = f"Defined at {m_link}"
                method_filepath = m_fp
                method_lineno = m_line
                method_end_lineno = m_end
        execution_steps.append(f"1. UI Click: User clicks button '{button_label_or_name}' on form view of '{model_name}'.")
        execution_steps.append(f"2. Method Invocation: Calls Python method '{method_name}()' ({method_link_str}).")

        if origin_states and target_state:
            orig_str = ", ".join(sorted(origin_states))
            execution_steps.append(f"3. State Transition: Transitions model '{model_name}' state from [{orig_str}] -> '{target_state}'.")
        else:
            execution_steps.append(f"3. State Transition: Executes method logic without state machine transition.")

        if required_groups:
            formatted_req = []
            for rg in sorted(required_groups):
                clean_rg = rg.lstrip("!")
                dname = get_group_display_name(G, clean_rg)
                prefix = "!" if rg.startswith("!") else ""
                formatted_req.append(f"{prefix}{clean_rg} ('{dname}')" if dname else rg)
            grp_str = ", ".join(formatted_req)
            _req_citations = format_xml_id_citations(sorted(required_groups))
            execution_steps.append(f"4. Security Requirement: Button restricted to groups [{grp_str}]. ({_req_citations})")
        else:
            grp_str = "None"
            execution_steps.append(f"4. Security Requirement: No button-level group restriction specified.")

        if invisible_condition:
            execution_steps.append(f"5. Visibility Condition: Button invisible condition '{invisible_condition}'.")

        tech_groups = technical_groups_among(G, sorted(required_groups))
        tech_req_notes = [
            f"'{tg.name}' [{tg.xmlid}] (paramètre: '{tg.setting_field}')" if tg.name
            else f"{tg.xmlid} (paramètre: '{tg.setting_field}')"
            for tg in tech_groups
        ]

        summary = (
            f"Button '{button_label_or_name}' on '{model_name}': "
            f"Calls '{method_name}()' ({method_link_str}). "
            f"Transition: [{', '.join(sorted(origin_states))}] -> '{target_state}'. "
            f"Required Groups: [{grp_str}]."
        )
        if tech_req_notes:
            summary += f" NOTE DE CONFIGURATION: Les groupes [{', '.join(tech_req_notes)}] sont des paramètres activables dans la configuration du module."
        if invisible_condition:
            summary += f" Visibility: invisible='{invisible_condition}'."

    available_to_requester: Optional[bool] = None
    unavailable_reason = ""
    if user_groups is not None:
        available_to_requester = _requester_satisfies_required_groups(G, sorted(required_groups), user_groups)
        if not available_to_requester:
            # Section 925 / 958: check if required groups are technical (settings-activated)
            tech_groups = technical_groups_among(G, sorted(required_groups))
            tech_xmlids = {tg.xmlid for tg in tech_groups}
            technical_groups = [(tg.xmlid, tg.setting_field) for tg in tech_groups]
            role_groups = [rg for rg in sorted(required_groups) if rg.lstrip("!") not in tech_xmlids]

            if technical_groups and not role_groups:
                # All required groups are technical feature flags
                settings_desc = ", ".join(
                    f"'{sf}'" for _, sf in technical_groups
                )
                unavailable_reason = (
                    f"Ce bouton/champ necessite l'activation du parametre de configuration "
                    f"{settings_desc} dans les Parametres du module. Lorsque cette option "
                    f"est activee, tous les utilisateurs internes y ont acces automatiquement "
                    f"-- il ne s'agit pas d'un droit de role individuel. "
                    f"(groupes techniques: [{', '.join(g for g, _ in technical_groups)}])"
                )
            elif technical_groups:
                # Mix of technical and role groups
                tech_desc = ", ".join(
                    f"{g} (parametre: '{sf}')" for g, sf in technical_groups
                )
                unavailable_reason = (
                    f"Ce bouton est restreint aux groupes [{', '.join(sorted(required_groups))}]. "
                    f"Certains sont des parametres de configuration ({tech_desc}), "
                    f"d'autres sont des roles ({', '.join(role_groups)}). "
                    f"Le demandeur ne fait partie d'aucun -- l'action n'est pas disponible "
                    f"pour lui dans l'interface."
                )
            else:
                unavailable_reason = (
                    f"Ce bouton est restreint aux groupes [{', '.join(sorted(required_groups))}], "
                    "dont le demandeur ne fait partie d'aucun -- l'action n'est pas disponible "
                    "pour lui dans l'interface (bouton absent ou grise), pas seulement documentee "
                    "comme restreinte."
                )
            summary += f" NON DISPONIBLE POUR LE DEMANDEUR : {unavailable_reason}"
            execution_steps.append(
                f"5. Disponibilite reelle : NON -- {unavailable_reason}"
            )
        else:
            execution_steps.append(
                "5. Disponibilite reelle : OUI -- le demandeur appartient a un groupe requis "
                "(ou aucun groupe n'est requis)."
            )

    return ButtonExecutionPathResult(
        button_identifier=button_label_or_name,
        model_name=model_name,
        method_name=method_name,
        origin_states=sorted(list(origin_states)),
        target_state=target_state,
        required_groups=sorted(list(required_groups)),
        execution_steps=execution_steps,
        summary_text=summary,
        available_to_requester=available_to_requester,
        unavailable_reason=unavailable_reason,
        method_tags=method_tags,
        method_filepath=method_filepath,
        method_lineno=method_lineno,
        method_end_lineno=method_end_lineno,
        evidence=_build_button_execution_evidence(
            button_label_or_name, model_name, method_name, method_exists,
            origin_states, target_state, required_groups,
            user_groups, available_to_requester,
        ),
    )
