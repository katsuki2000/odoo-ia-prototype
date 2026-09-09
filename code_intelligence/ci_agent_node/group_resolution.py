"""
code_intelligence/ci_agent_node/group_resolution.py

Real Odoo group DB ID -> xml_id resolution, extracted from the former
ci_agent_node.py monolith (refactor, see todo/contexte.txt). Behavior
unchanged: core.graph keeps an independent copy of these globals
(re-imported by name from code_intelligence.ci_agent_node), and
_get_admin_rpc_client() explicitly syncs against core.graph's copy via
sys.modules so a reset on either side is mirrored on the other.
"""

import logging

logger = logging.getLogger(__name__)

_GROUP_XMLID_CACHE: dict = {}
_ADMIN_RPC_CLIENT = None
_ADMIN_RPC_UID = None


def _get_admin_rpc_client():
    """Lazy singleton admin XML-RPC client + uid, reused across requests --
    pure static-metadata lookups only (group xml_id resolution), never used
    for anything requiring the actual requester's own rights.

    core.graph holds an independent copy of these globals (re-imported by
    name); a reset on that copy is now mirrored here too, so a stale client
    left over from an earlier test can never leak through (contexte.txt
    section 256).
    """
    global _ADMIN_RPC_CLIENT, _ADMIN_RPC_UID
    import sys
    g_mod = sys.modules.get("core.graph")
    if g_mod is not None:
        target_client = getattr(g_mod, "_ADMIN_RPC_CLIENT", None)
        target_uid = getattr(g_mod, "_ADMIN_RPC_UID", None)
        if target_client is not None:
            _ADMIN_RPC_CLIENT, _ADMIN_RPC_UID = target_client, target_uid
            return target_client, target_uid
        _ADMIN_RPC_CLIENT = None
        _ADMIN_RPC_UID = None

    if _ADMIN_RPC_CLIENT is None:
        from code_intelligence.live.rpc_client import OdooRpcClient
        client = OdooRpcClient()
        _ADMIN_RPC_UID = client.authenticate_admin()
        _ADMIN_RPC_CLIENT = client
        if g_mod is not None:
            g_mod._ADMIN_RPC_CLIENT = client
            g_mod._ADMIN_RPC_UID = _ADMIN_RPC_UID
    return _ADMIN_RPC_CLIENT, _ADMIN_RPC_UID


def _resolve_user_group_xmlids(group_ids) -> list:
    global _GROUP_XMLID_CACHE
    import sys
    g_mod = sys.modules.get("core.graph")
    cache = getattr(g_mod, "_GROUP_XMLID_CACHE", None) if g_mod is not None else _GROUP_XMLID_CACHE
    if cache is None:
        cache = _GROUP_XMLID_CACHE

    if not group_ids:
        return []

    # If any group_id is already an xml_id string (contains a dot or non-numeric), populate cache directly
    for g in group_ids:
        if isinstance(g, str) and ("." in g or not g.isdigit()):
            cache[g] = g
            _GROUP_XMLID_CACHE[g] = g

    uncached = [g for g in group_ids if g not in cache]
    if uncached:
        try:
            client, admin_uid = _get_admin_rpc_client()
            resolved = client.get_group_xmlids(admin_uid, uncached)
            cache.update(resolved)
            _GROUP_XMLID_CACHE.update(resolved)
        except Exception as e:
            logger.error(
                "Group ID -> xml_id resolution failed for %s: %s. "
                "These groups will be treated as unresolved (fail closed).",
                uncached, e,
            )

    return [cache[g] for g in group_ids if g in cache]
