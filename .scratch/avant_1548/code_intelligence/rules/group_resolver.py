"""
code_intelligence/deterministic/group_resolver.py

Tolerant group identifier resolution and transitive group hierarchy expansion
for Odoo res.groups (implied_ids / IMPLIES edges).
"""

from pathlib import Path
import unicodedata
from typing import Dict, List, Optional, Set
import networkx as nx
from rapidfuzz import fuzz

FUZZY_GROUP_MATCH_THRESHOLD = 75

_PARSED_MODULE_GROUPS: Dict[str, Dict[str, str]] = {}


def _lookup_group_name_in_xml(group_xml_id: str) -> str:
    """Dynamic resolution of res.groups display name from XML files in addons paths."""
    from config.settings import CORE_ADDONS_PATH, CUSTOM_ADDONS_PATH
    from code_intelligence.extractor.xml import parse_groups_from_xml

    mod_name = group_xml_id.split(".")[0] if "." in group_xml_id else None
    bare_id = group_xml_id.split(".")[-1]

    candidate_roots = []
    if CORE_ADDONS_PATH:
        candidate_roots.append(Path(CORE_ADDONS_PATH))
    if CUSTOM_ADDONS_PATH:
        candidate_roots.append(Path(CUSTOM_ADDONS_PATH))

    candidate_modules = [mod_name] if mod_name else []

    for root_dir in candidate_roots:
        if not root_dir.exists():
            continue
        if candidate_modules:
            dirs_to_check = [root_dir / m for m in candidate_modules if (root_dir / m).is_dir()]
        else:
            dirs_to_check = [d for d in root_dir.iterdir() if d.is_dir()]

        for mod_dir in dirs_to_check:
            m_name = mod_dir.name
            if m_name not in _PARSED_MODULE_GROUPS:
                _PARSED_MODULE_GROUPS[m_name] = {}
                for xml_file in mod_dir.rglob("*.xml"):
                    for r in parse_groups_from_xml(xml_file):
                        if r.name:
                            _PARSED_MODULE_GROUPS[m_name][r.xml_id] = r.name
                            _PARSED_MODULE_GROUPS[m_name][f"{m_name}.{r.xml_id}"] = r.name

            mod_cache = _PARSED_MODULE_GROUPS[m_name]
            if group_xml_id in mod_cache:
                return mod_cache[group_xml_id]
            if bare_id in mod_cache:
                return mod_cache[bare_id]

    return ""


def get_group_display_name(G: Optional[nx.DiGraph], group_identifier: str) -> str:
    """Return a translated group label, qualified by its application if ambiguous."""
    if not group_identifier:
        return ""

    clean_id = group_identifier.strip()

    if G is not None:
        node_id = f"group:{clean_id}"
        if node_id in G:
            return _qualified_group_label(G, node_id)

        if "." not in clean_id:
            suffix = f".{clean_id}"
            matches = [
                node_id for node_id, data in G.nodes(data=True)
                if node_id.startswith("group:")
                and node_id.endswith(suffix)
                and _localized_label(data)
            ]
            if len(matches) == 1:
                return _qualified_group_label(G, matches[0])
        else:
            short_id = clean_id.split(".")[-1]
            short_node = f"group:{short_id}"
            if short_node in G:
                return _qualified_group_label(G, short_node)

    # Dynamic XML lookup across addons (cached in _PARSED_MODULE_GROUPS)
    return _lookup_group_name_in_xml(clean_id)


def format_groups(G: Optional[nx.DiGraph], groups) -> List[str]:
    """Sorted "xml_id ('label')" entries, the bare xml_id when no label is known."""
    return [
        f"{group} ('{label}')" if (label := get_group_display_name(G, group)) else group
        for group in sorted(groups)
    ]


def _localized_label(data: dict) -> str:
    translations = [
        item for item in data.get("business_labels") or []
        if str(item.get("label") or "").strip()
    ]
    french = [
        item for item in translations
        if str(item.get("language") or "").casefold().replace("-", "_").split("_", 1)[0] == "fr"
    ]
    if french:
        return sorted(str(item["label"]).strip() for item in french)[0]
    if translations:
        return sorted(str(item["label"]).strip() for item in translations)[0]
    return str(data.get("name") or "").strip()


def _application_label(G: nx.DiGraph, data: dict) -> str:
    category_id = str(data.get("category_id") or "").strip()
    if category_id:
        category_node = category_id if category_id.startswith("category:") else f"category:{category_id}"
        if G.has_node(category_node):
            label = _localized_label(G.nodes[category_node])
            if label:
                return label
        category_name = category_id.split(".", 1)[-1]
        category_name = category_name.removeprefix("module_category_")
        return category_name.replace("_", " ").strip().title()
    xml_id = str(data.get("xml_id") or "")
    return xml_id.split(".", 1)[0].replace("_", " ").title()


def _qualified_group_label(G: nx.DiGraph, node_id: str) -> str:
    data = G.nodes[node_id]
    label = _localized_label(data)
    if not label:
        return ""
    collisions = [
        other_id for other_id, other_data in G.nodes(data=True)
        if other_id.startswith("group:")
        and other_id != node_id
        and _localized_label(other_data).casefold() == label.casefold()
    ]
    if not collisions:
        return label
    application = _application_label(G, data)
    return f"{application} : {label}" if application else label


def _group_short_name(xml_id: str) -> str:
    """Part of a group xml_id after the last '.', used as a tolerant
    fallback when a full module-qualified id doesn't match exactly."""
    return xml_id.rsplit(".", 1)[-1]


def _group_display_name(G: nx.DiGraph, full_xml_id: str) -> str:
    """Human-readable name of a group node (e.g. 'Avoirs - Visibilite
    Regionale'), looked up from the graph. Empty string if not found."""
    return get_group_display_name(G, full_xml_id)


def _strip_group_prefix(s: str) -> str:
    """
    Strip the Odoo naming-convention prefix "group_" (e.g.
    "group_regional" -> "regional") before fuzzy-matching against a
    group's human-readable display name. Without this, the prefix
    dilutes the match score below threshold: "group_regional" vs
    "Avoirs - Visibilite Regionale" scores ~70 (just under the 75
    threshold) via partial_ratio, while "regional" alone (prefix
    stripped) scores much higher, since "group_" has no counterpart
    in the display name.
    """
    return s[len("group_"):] if s.lower().startswith("group_") else s


def _fold_accents(s: str) -> str:
    """
    Strip accents for accent-insensitive fuzzy matching. NFC normalization
    alone (used elsewhere for exact alias lookup) is NOT enough here: it
    only picks a canonical encoding for an accented character, it never
    removes the accent itself.
    """
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if not unicodedata.combining(c))


def _group_fuzzy_matches_display_name(G: nx.DiGraph, user_group: str, rule_group_full_xml_id: str) -> bool:
    """
    Fuzzy-match a user-supplied group identifier against a specific group's
    human-readable display name (e.g. "Avoirs - Visibilite Nationale").
    """
    display_name = _group_display_name(G, rule_group_full_xml_id)
    if not display_name:
        return False
    folded_display_name = _fold_accents(display_name.lower())
    folded_user_group = _fold_accents(_strip_group_prefix(user_group).lower())
    score = max(
        fuzz.token_set_ratio(folded_user_group, folded_display_name),
        fuzz.partial_ratio(folded_user_group, folded_display_name),
    )
    return score >= FUZZY_GROUP_MATCH_THRESHOLD


def resolve_group_identifier(G: nx.DiGraph, user_group: str, candidate_full_xml_ids: List[str]) -> Optional[str]:
    """
    Shared tolerant group-identifier resolver, used by both
    evaluate_record_rules() and who_has_access_to() so an LLM tool call
    supplying an imprecise group name (short name, missing module prefix,
    or a bare business word like "regional" instead of any technical
    identifier) resolves consistently across every tool, not just the one
    that happened to be patched first.

    Tried in order, from most to least strict:
      1. Exact match on the full xml_id.
      2. Short-name match (part after the last '.').
      3. Fuzzy match against the group's human-readable display name.

    Returns the matching full_xml_id from candidate_full_xml_ids, or None
    if no candidate matches by any of the three methods.
    """
    if user_group in candidate_full_xml_ids:
        return user_group

    short_user_group = _group_short_name(user_group)
    for candidate in candidate_full_xml_ids:
        if _group_short_name(candidate) == short_user_group:
            return candidate

    for candidate in candidate_full_xml_ids:
        if _group_fuzzy_matches_display_name(G, user_group, candidate):
            return candidate

    return None


def _expand_implied_user_groups(G: nx.DiGraph, user_group: str, user_group_set: Set[str]):
    """
    Recursively add every broader group implied BY user_group (Odoo implied_ids
    semantics: membership in user_group automatically grants membership in
    every group it implies, transitively).

    Edge convention in graph_builder.py:
        specific_group --IMPLIES--> broader_group
    So the broader groups a user inherits are reached by walking OUTGOING
    IMPLIES edges from user_group.
    """
    group_node = f"group:{user_group}"
    if group_node not in G:
        return

    for _, broader_node, edge_data in G.out_edges(group_node, data=True):
        if edge_data.get("edge_type") in ("IMPLIES", "IMPLIES_CONFIGURABLE"):
            broader_group_id = broader_node.replace("group:", "")
            if broader_group_id not in user_group_set:
                user_group_set.add(broader_group_id)
                _expand_implied_user_groups(G, broader_group_id, user_group_set)


def _expand_inheriting_acl_groups(
    G: nx.DiGraph,
    acl_group: str,
    allowed_groups: Set[str],
    inherited_via: Optional[Dict[str, str]] = None,
    _root_acl_group: Optional[str] = None,
) -> Dict[str, str]:
    """
    Recursively add every higher-privilege group that IMPLIES acl_group.

    Edge convention in graph_builder.py:
        higher_group --IMPLIES--> acl_group
    When an ACL grants permission to acl_group, any higher_group that implies
    acl_group automatically inherits that ACL permission. Reached by walking
    INCOMING IMPLIES edges to acl_group.

    Section 848: also returns `inherited_via` -- a {higher_group: root_acl_group}
    map recording, for every group added ONLY because it implies acl_group
    (not because it has the ACL itself), which group actually holds the direct
    ACL. Without this, a flat `allowed_groups` set cannot distinguish "has the
    ACL" from "inherits it via implied_ids" -- observed directly on ACC-Q1
    (account.move, WRITE/CREATE/UNLINK): account.group_account_manager's own
    direct ACL is perm_read=1 only, the actual grant belongs to
    account.group_account_invoice which it implies, but the flat set put both
    on equal footing, and the LLM then stated the manager "possede" the
    write/create/unlink rights directly, contradicting the question's own
    (correct) premise and never mentioning the implied_ids mechanism the
    reference answer calls essential.
    """
    if inherited_via is None:
        inherited_via = {}
    if _root_acl_group is None:
        _root_acl_group = acl_group

    group_node = f"group:{acl_group}"
    if group_node not in G:
        return inherited_via

    for higher_node, _, edge_data in G.in_edges(group_node, data=True):
        if edge_data.get("edge_type") == "IMPLIES":
            higher_group_id = higher_node.replace("group:", "")
            if higher_group_id not in allowed_groups:
                allowed_groups.add(higher_group_id)
                inherited_via[higher_group_id] = _root_acl_group
                _expand_inheriting_acl_groups(
                    G, higher_group_id, allowed_groups, inherited_via, _root_acl_group
                )
    return inherited_via
