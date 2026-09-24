"""
Technical groups are switched on by a res.config.settings option (implied_group),
not assigned to users as a role. The graph marks them with group_type="technical".
"""

from typing import List, NamedTuple

import networkx as nx


class TechnicalGroup(NamedTuple):
    xmlid: str
    setting_field: str
    name: str


def technical_groups_among(G: nx.DiGraph, group_xmlids: List[str]) -> List[TechnicalGroup]:
    found = []
    for xmlid in group_xmlids:
        clean_xmlid = xmlid.lstrip("!")
        node = f"group:{clean_xmlid}"
        if G.has_node(node) and G.nodes[node].get("group_type") == "technical":
            attrs = G.nodes[node]
            found.append(TechnicalGroup(clean_xmlid, attrs.get("setting_field", ""), attrs.get("name", "")))
    return found


def format_technical_group_note(technical_groups: List[TechnicalGroup]) -> str:
    described = ", ".join(
        f"'{group.name}' [{group.xmlid}] (paramètre: '{group.setting_field}')" if group.name
        else f"{group.xmlid} (paramètre: '{group.setting_field}')"
        for group in technical_groups
    )
    return (
        f"NOTE DE CONFIGURATION: Les groupes {described} sont des paramètres activables "
        "dans la configuration du module, pas des rôles attribués individuellement ; "
        "la condition porte sur l'utilisateur désigné par l'expression qui appelle has_group. "
        "Nommer ce paramètre par son libellé exact entre guillemets, sans le traduire ni le reformuler."
    )
