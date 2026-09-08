"""
code_intelligence/deterministic/menu_view_finder.py

Dynamic view injection (get_view / fields_view_get) and UI Menu item
lookup for actions not found in static button declarations.
"""

from pathlib import Path
import re
from typing import Optional
import networkx as nx

from code_intelligence.deterministic.button_path_models import ButtonExecutionPathResult
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
        grp_str = ", ".join(sorted(menu_groups)) if menu_groups else "None"
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
        )

    return None
