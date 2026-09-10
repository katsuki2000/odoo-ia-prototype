"""
code_intelligence/graph/security_nodes.py

Sub-graph node and edge builders for security, rules, ACLs, server actions, and automations.
"""

from typing import Callable, Dict, Optional
import networkx as nx

from code_intelligence.ontology.tags import BehavioralTag, TechnicalTag
from code_intelligence.utils import resolve_model_xmlref
from .models import ParsedModule, ResolvedSymbolRegistry


def add_security_group_nodes(
    G: nx.DiGraph,
    registry: ResolvedSymbolRegistry,
    modules_dict: Dict[str, ParsedModule],
    domain_force_references_state_fn: Callable[[Optional[str]], bool],
):
    """Add Group, Rule, AccessEntry, ServerAction, and AutomationRule nodes + security edges."""
    # 1. Groups & Group IMPLIES Group hierarchy
    for full_xml_id, grp in registry.groups.items():
        if "." not in full_xml_id:
            continue
        grp_node_id = f"group:{full_xml_id}"
        G.add_node(
            grp_node_id,
            node_type="Group",
            xml_id=full_xml_id,
            name=grp.name,
            category_id=grp.category_id,
        )

        for parent_grp in grp.implied_ids:
            parent_node_id = f"group:{parent_grp}"
            G.add_edge(grp_node_id, parent_node_id, edge_type="IMPLIES")

    # 2. Rules & Model RESTRICTED_BY Rule -> Rule APPLIES_TO_GROUP Group
    for full_xml_id, rule in registry.rules.items():
        if "." not in full_xml_id:
            continue
        if not getattr(rule, "active", True):
            continue
        rule_node_id = f"rule:{full_xml_id}"
        rule_behavioral_tags = [BehavioralTag.VISIBILITY_RULE.value]
        if domain_force_references_state_fn(rule.domain_force):
            rule_behavioral_tags.append(BehavioralTag.WORKFLOW_RULE.value)
        G.add_node(
            rule_node_id,
            node_type="Rule",
            xml_id=full_xml_id,
            name=rule.name,
            domain_force=rule.domain_force,
            filepath=rule.filepath,
            lineno=rule.lineno,
            perm_read=rule.perm_read,
            perm_write=rule.perm_write,
            perm_create=rule.perm_create,
            perm_unlink=rule.perm_unlink,
            behavioral_tags=rule_behavioral_tags,
            technical_tags=[TechnicalTag.RECORD_RULE.value],
        )

        if rule.model_id:
            raw_m = resolve_model_xmlref(rule.model_id)
            model_node_id = f"model:{raw_m}"
            G.add_edge(model_node_id, rule_node_id, edge_type="RESTRICTED_BY")

        for grp_ref in rule.groups_id:
            mod_prefix = full_xml_id.split(".")[0] if "." in full_xml_id else "base"
            full_grp = grp_ref if "." in grp_ref else f"{mod_prefix}.{grp_ref}"
            grp_node_id = f"group:{full_grp}"
            G.add_edge(rule_node_id, grp_node_id, edge_type="APPLIES_TO_GROUP")

    # 3. CSV Access Control Entries (Model GRANTED_BY AccessEntry)
    for mod_name, mod in modules_dict.items():
        for acl in mod.acl_entries:
            acl_node_id = f"acl:{mod_name}.{acl.xml_id}"
            G.add_node(
                acl_node_id,
                node_type="AccessEntry",
                name=acl.name,
                perm_read=acl.perm_read,
                perm_write=acl.perm_write,
                perm_create=acl.perm_create,
                perm_unlink=acl.perm_unlink,
                all_authenticated=acl.all_authenticated,
                behavioral_tags=[BehavioralTag.VISIBILITY_RULE.value],
                technical_tags=[TechnicalTag.ACL.value],
            )

            raw_m = resolve_model_xmlref(acl.model_id)
            model_node_id = f"model:{raw_m}"
            G.add_edge(model_node_id, acl_node_id, edge_type="GRANTED_BY")

            if acl.group_id:
                grp_node_id = f"group:{acl.group_id}"
                G.add_edge(acl_node_id, grp_node_id, edge_type="APPLIES_TO_GROUP")

    # 4. Server Actions (ir.actions.server) & Automations (base.automation)
    for full_xml_id, sa in registry.server_actions.items():
        if "." not in full_xml_id:
            continue
        sa_node_id = f"server_action:{full_xml_id}"
        G.add_node(
            sa_node_id,
            node_type="ServerAction",
            xml_id=full_xml_id,
            name=sa.name,
            model_id=sa.model_id,
            state=sa.state,
            code=sa.code,
            action_type=getattr(sa, "action_type", "server_action"),
            user_id=getattr(sa, "user_id", ""),
            interval_number=getattr(sa, "interval_number", 1),
            interval_type=getattr(sa, "interval_type", ""),
            behavioral_tags=[],
            technical_tags=[TechnicalTag.SERVER_ACTION.value],
        )

        if sa.model_id:
            raw_m = resolve_model_xmlref(sa.model_id)
            model_node_id = f"model:{raw_m}"
            G.add_edge(sa_node_id, model_node_id, edge_type="TARGETS_MODEL")

    for full_xml_id, ba in registry.base_automations.items():
        if "." not in full_xml_id:
            continue
        ba_node_id = f"automation:{full_xml_id}"
        G.add_node(
            ba_node_id,
            node_type="AutomationRule",
            xml_id=full_xml_id,
            name=ba.name,
            model_id=ba.model_id,
            trigger=ba.trigger,
            behavioral_tags=[],
            technical_tags=[TechnicalTag.CRON.value],
        )

        if ba.model_id:
            raw_m = resolve_model_xmlref(ba.model_id)
            model_node_id = f"model:{raw_m}"
            G.add_edge(ba_node_id, model_node_id, edge_type="TRIGGERED_BY")

        for sa_ref in ba.action_server_ids:
            mod_prefix = full_xml_id.split(".")[0] if "." in full_xml_id else "base"
            full_sa = sa_ref if "." in sa_ref else f"{mod_prefix}.{sa_ref}"
            sa_node_id = f"server_action:{full_sa}"
            G.add_edge(ba_node_id, sa_node_id, edge_type="EXECUTES_ACTION")


__all__ = ["add_security_group_nodes"]
