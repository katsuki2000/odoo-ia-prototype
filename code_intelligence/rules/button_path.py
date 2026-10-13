"""
code_intelligence/deterministic/button_path_models.py

Data structures and evidence generation for Odoo button execution paths and UI field inspection.
"""

from dataclasses import dataclass, field
import re
from typing import List, Optional, Set, Tuple

from core.evidence.evidence import Evidence, EvidenceSourceType, make_evidence
from code_intelligence.graph.workflow_extraction import workflow_transition_records

DISPLAY_CAUSES_MARKER = "[FAIT DÉTERMINISTIQUE -- CAUSES DE NON-AFFICHAGE]"

_NEGATED_EQUALITY = re.compile(r"""^\s*([\w.]+)\s*!=\s*['"]([^'"]+)['"]\s*$""")
_NEGATED_MEMBERSHIP = re.compile(r"""^\s*([\w.]+)\s+not\s+in\s*[(\[]([^)\]]*)[)\]]\s*$""")
_QUOTED_LITERAL = re.compile(r"""['"]([^'"]+)['"]""")


def parse_visibility_rule(invisible_condition: str) -> Optional[Tuple[str, List[str]]]:
    """Turn a pure negated `invisible` expression into (field, values for which the
    element is visible). Compound expressions return None: they are never guessed."""
    match = _NEGATED_EQUALITY.match(invisible_condition or "")
    if match:
        return match.group(1), [match.group(2)]
    match = _NEGATED_MEMBERSHIP.match(invisible_condition or "")
    if match:
        values = _QUOTED_LITERAL.findall(match.group(2))
        if values:
            return match.group(1), values
    return None


def _describe_visible_when(rule: Tuple[str, List[str]]) -> str:
    field_name, values = rule
    if len(values) == 1:
        return f"{field_name} == '{values[0]}'"
    return f"{field_name} in ({', '.join(repr(v) for v in values)})"


def _values_named_in(text: str, values: List[str]) -> List[str]:
    folded_text = _fold_accents(text).lower()
    return [
        value for value in values
        if re.search(rf"(?<!\w){re.escape(_fold_accents(value).lower())}(?!\w)", folded_text)
    ]


def _format_display_causes(satisfied: List[str], blocking: List[str]) -> str:
    return (
        f"{DISPLAY_CAUSES_MARKER} Conditions d'affichage satisfaites d'après la question : "
        f"{'; '.join(satisfied)}. Cause bloquante : {'; '.join(blocking)}. "
        "Aucune autre condition d'affichage n'est déclarée sur ce bouton ; l'expression "
        "`invisible` indique quand le bouton est masqué et n'est pas une anomalie."
    )


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
    if not match or not re.search(r"invers|erron|erreur|anomalie|bug|bogue", final_answer, re.IGNORECASE):
        return final_answer
    field_name, visible_state = match.groups()

    def _is_erroneous_visibility_block(b: str) -> bool:
        has_vis_context = bool(re.search(
            r"visibilit[eé]|invisible|" + re.escape(field_name),
            b,
            re.IGNORECASE,
        ))
        has_error_claim = bool(re.search(
            r"invers|erron|erreur|anomalie|bug|bogue",
            b,
            re.IGNORECASE,
        ))
        return has_vis_context and has_error_claim

    blocks = re.split(r"\n\s*\n", final_answer)
    blocks = [block for block in blocks if not _is_erroneous_visibility_block(block)]
    corrected = "\n\n".join(blocks).rstrip()
    corrected = re.sub(
        r"pour\s+(?:deux|plusieurs)\s+raisons(?:\s+principales)?\s*:",
        "pour la raison principale suivante :",
        corrected,
        flags=re.IGNORECASE,
    )
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
    satisfied_conditions: List[str] = field(default_factory=list)
    blocking_causes: List[str] = field(default_factory=list)


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
from code_intelligence.rules.model_suggestions import model_not_found_message
from code_intelligence.rules.group_resolver import (
    _expand_implied_user_groups,
    _fold_accents,
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


_METHOD_PREFIXES = ("action_", "button_")
_MAX_NEAR_BUTTONS = 5
_MAX_LISTED_BUTTONS = 12


def _strip_method_prefix(name: str) -> str:
    for prefix in _METHOD_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def _is_exact_button_match(target: str, method_name: str, label: str) -> bool:
    """A button is identified by its label or its method name, Odoo's conventional
    `action_`/`button_` prefix being optional. Merely containing the requested word
    is not enough: 'create' is inside 'action_create_invoice' without being it."""
    if label and target == label:
        return True
    return bool(method_name) and _strip_method_prefix(target) == _strip_method_prefix(method_name)


def _is_near_button_match(target: str, method_name: str, label: str) -> bool:
    return bool(
        (label and (target in label or label in target))
        or (method_name and (target in method_name or method_name in target))
    )


def _format_near_buttons(near_buttons: List[Tuple[str, str]], limit: int = _MAX_NEAR_BUTTONS) -> str:
    labels_by_method: dict = {}
    for method, label in near_buttons:
        labels = labels_by_method.setdefault(method, [])
        if label and label not in labels:
            labels.append(label)
    parts = []
    for method, labels in list(labels_by_method.items())[:limit]:
        shown = ", ".join(f"'{label}'" for label in labels)
        parts.append(f"'{method}()' (label: {shown})" if labels else f"'{method}()'")
    return ", ".join(parts)


def _transition_records_of(G: nx.DiGraph, model_name: str):
    for u, v, edge_data in G.edges(data=True):
        if edge_data.get("edge_type") != "TRANSITIONS_VIA":
            continue
        origin_node = G.nodes.get(u, {})
        origin_model = origin_node.get("model") or u.removeprefix("state:").rsplit(".", 1)[0]
        if origin_model != model_name:
            continue
        for record in workflow_transition_records(edge_data):
            yield u, v, record


def _button_edges_of(G: nx.DiGraph, model_name: str):
    model_node_id = f"model:{model_name}"
    if model_node_id not in G:
        return
    for _, _, edge_data in G.out_edges(model_node_id, data=True):
        if edge_data.get("edge_type") == "HAS_BUTTON":
            yield edge_data


def _declared_buttons(G: nx.DiGraph, model_name: str) -> List[Tuple[str, str]]:
    records = [record for _, _, record in _transition_records_of(G, model_name)]
    records.extend(_button_edges_of(G, model_name))
    pairs = {
        ((record.get("method_name") or "").strip(), (record.get("label_bouton") or "").strip())
        for record in records
    }
    return sorted(pair for pair in pairs if pair[0])


def button_execution_path(
    G: nx.DiGraph,
    button_label_or_name: str,
    model_name: str,
    user_groups: Optional[List[str]] = None,
    premise_text: str = "",
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
            summary_text=model_not_found_message(G, model_name)
        )

    method_name = ""
    origin_states: Set[str] = set()
    target_states: List[str] = []
    required_groups: Set[str] = set()
    execution_steps: List[str] = []

    candidate_transitions = []
    near_buttons: List[Tuple[str, str]] = []
    target_clean = button_label_or_name.strip().lower()
    for u, v, record in _transition_records_of(G, model_name):
        m_name = (record.get("method_name") or "").strip()
        btn_label = (record.get("label_bouton") or "").strip()
        if _is_exact_button_match(target_clean, m_name.lower(), btn_label.lower()):
            candidate_transitions.append((m_name, u, v, record))
        elif _is_near_button_match(target_clean, m_name.lower(), btn_label.lower()):
            near_buttons.append((m_name, btn_label))

    if candidate_transitions:
        candidate_methods = sorted({item[0] for item in candidate_transitions if item[0]})
        if len(candidate_methods) > 1:
            return ButtonExecutionPathResult(
                button_identifier=button_label_or_name,
                model_name=model_name,
                summary_text=(
                    f"Button '{button_label_or_name}' on '{model_name}' is ambiguous: "
                    f"multiple exact workflow matches exist for methods "
                    f"{', '.join(candidate_methods)}. No transition was selected."
                ),
            )
        chosen_method = candidate_methods[0] if candidate_methods else ""
        for m_name, u, v, edge_data in candidate_transitions:
            if m_name == chosen_method:
                method_name = m_name
                origin_node = G.nodes.get(u, {})
                target_node = G.nodes.get(v, {})
                orig_st = origin_node.get("state_value") or u.removeprefix(f"state:{model_name}.")
                targ_st = target_node.get("state_value") or v.removeprefix(f"state:{model_name}.")
                origin_states.add(orig_st)
                if targ_st not in target_states:
                    target_states.append(targ_st)
                groups_req = edge_data.get("groupe_requis", [])
                if isinstance(groups_req, list):
                    required_groups.update(groups_req)

    target_state = " or ".join(target_states)

    invisible_condition = ""
    if not method_name:
        candidate_buttons = []
        for edge_data in _button_edges_of(G, model_name):
            m_name = (edge_data.get("method_name") or "").strip()
            btn_label = (edge_data.get("label_bouton") or "").strip()
            if _is_exact_button_match(target_clean, m_name.lower(), btn_label.lower()):
                candidate_buttons.append((m_name, edge_data))
            elif _is_near_button_match(target_clean, m_name.lower(), btn_label.lower()):
                near_buttons.append((m_name, btn_label))
        if candidate_buttons:
            candidate_methods = sorted({
                item[0] for item in candidate_buttons if item[0]
            })
            if len(candidate_methods) > 1:
                return ButtonExecutionPathResult(
                    button_identifier=button_label_or_name,
                    model_name=model_name,
                    summary_text=(
                        f"Button '{button_label_or_name}' on '{model_name}' is ambiguous: "
                        f"multiple exact XML button declarations map to methods "
                        f"{', '.join(candidate_methods)}. No method was selected."
                    ),
                )
            method_name, edge_data = candidate_buttons[0]
            groups_req = edge_data.get("groupe_requis", [])
            if isinstance(groups_req, list):
                required_groups.update(groups_req)
            invisible_condition = edge_data.get("invisible", "")

    button_identified = bool(method_name)

    if not method_name:
        field_view_res = _find_field_in_xml_views(G, model_name, button_label_or_name, user_groups=user_groups)
        if field_view_res is not None:
            return field_view_res

    if not method_name:
        method_name = button_label_or_name if button_label_or_name.startswith("action_") or button_label_or_name.startswith("_") else f"action_{button_label_or_name.lower()}"

    visibility_rule = parse_visibility_rule(invisible_condition)

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
        if button_identified:
            summary = (
                f"Button or UI element '{button_label_or_name}' on '{model_name}': "
                f"Neither button declaration nor method '{method_name}()' found in knowledge graph. "
                f"Transition: [] -> ''. "
                f"Required Groups: [None]."
            )
        else:
            summary = (
                f"Button or UI element '{button_label_or_name}' on '{model_name}' {NOT_FOUND_MARKER}: "
                f"no declared button or method matches that name exactly. "
                f"Transition: [] -> ''. "
                f"Required Groups: [None]."
            )
            if near_buttons:
                summary += (
                    f" Closest declared buttons (not an exact match, so nothing is asserted about them; "
                    f"call again with one of these exact names only if it is the one asked about): "
                    f"{_format_near_buttons(near_buttons)}."
                )
            else:
                declared_buttons = _declared_buttons(G, model_name)
                if declared_buttons:
                    summary += (
                        " No declared button is close to that name; button labels are stored as declared "
                        "in the instance, possibly in another language than the question. Declared buttons "
                        "on this model (nothing is asserted about them; call again with the exact name of "
                        "the one the question is about, or use describe_workflow for the process): "
                        f"{_format_near_buttons(declared_buttons, _MAX_LISTED_BUTTONS)}."
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
            if visibility_rule:
                summary += f" (visible quand {_describe_visible_when(visibility_rule)})"

    available_to_requester: Optional[bool] = None
    unavailable_reason = ""
    button_resolved = button_identified or method_exists or bool(invisible_condition)
    if user_groups is not None and button_resolved:
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

    satisfied_conditions: List[str] = []
    blocking_causes: List[str] = []
    named_values = _values_named_in(premise_text, visibility_rule[1]) if visibility_rule else []
    if named_values:
        satisfied_conditions.append(_describe_visible_when((visibility_rule[0], named_values)))
    if available_to_requester is False:
        blocking_causes.append("le demandeur n'appartient à aucun des groupes requis")
    if satisfied_conditions and blocking_causes:
        summary += " " + _format_display_causes(satisfied_conditions, blocking_causes)

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
            user_groups if button_resolved else None, available_to_requester,
        ),
        satisfied_conditions=satisfied_conditions,
        blocking_causes=blocking_causes,
    )
