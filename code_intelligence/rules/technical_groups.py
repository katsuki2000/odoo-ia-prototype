"""
Technical groups are switched on by a res.config.settings option (implied_group),
not assigned to users as a role. The graph marks them with group_type="technical".
"""

from typing import List, NamedTuple

import networkx as nx

from code_intelligence.rules.group_resolver import get_group_display_name


class TechnicalGroup(NamedTuple):
    xmlid: str
    setting_field: str
    name: str


def technical_groups_among(G: nx.DiGraph, group_xmlids: List[str]) -> List[TechnicalGroup]:
    found = []
    for xmlid in group_xmlids:
        clean_xmlid = xmlid.lstrip("!")
        node = f"group:{clean_xmlid}"
        if G.has_node(node):
            attrs = G.nodes[node]
            is_tech = attrs.get("group_type") == "technical"
            setting_field = attrs.get("setting_field", "")
            if not is_tech:
                short_name = clean_xmlid.split(".")[-1]
                field_node = f"field:res.config.settings.{short_name}"
                if G.has_node(field_node) and attrs.get("category_id") in ("base.module_category_hidden", None):
                    is_tech = True
                    setting_field = short_name
            if is_tech:
                grp_name = attrs.get("name", "") or get_group_display_name(G, clean_xmlid)
                found.append(TechnicalGroup(clean_xmlid, setting_field, grp_name))
    return found


def format_technical_group_note(technical_groups: List[TechnicalGroup]) -> str:
    described = ", ".join(
        f"'{group.name}' [{group.xmlid}] (paramètre: '{group.setting_field}', xml_id: {group.xmlid})" if group.name
        else f"{group.xmlid} (paramètre: '{group.setting_field}', xml_id: {group.xmlid})"
        for group in technical_groups
    )
    return (
        f"NOTE DE CONFIGURATION: Les groupes {described} sont des paramètres activables "
        "dans la configuration du module, pas des rôles attribués individuellement ; "
        "la condition porte sur l'utilisateur désigné par l'expression qui appelle has_group. "
        "Nommer ce paramètre par son libellé exact entre guillemets, sans le traduire ni le reformuler."
    )
