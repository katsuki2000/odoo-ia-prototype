"""
code_intelligence/tests/test_j23_24_group_id_xmlid_resolution.py

Regression for a J23-24 review finding: the demandeur's real Odoo groups
arrive from the JWT as res.groups DATABASE IDs (miro_ai/controllers/main.py:
`groups = [g.id for g in user.groups_id]`), but the entire knowledge graph
(resolve_group_identifier, evaluer_regles_enregistrement,
authorization_gate._has_elevated_access) identifies groups by XML-ID
(module.name), built statically from XML extraction. Without translation,
every real logged-in user was silently treated as belonging to no group at
all -- gating and ir.rule evaluation both failed closed for everyone,
defeating Bloc 7's "filtered by the demandeur's real rights" requirement.

These tests mock the RPC layer (no live Odoo needed) to prove:
  1. the bug reproduces with raw, unresolved integer IDs (as they arrive
     from the JWT today, before this fix's call site is wired in);
  2. resolving through _resolve_user_group_xmlids() fixes it end-to-end
     against the real gate_observation()/_has_elevated_access() code path.
"""
import networkx as nx
import pytest

from code_intelligence.authorization_gate import gate_observation, _has_elevated_access


def _build_graph_with_acl(model_name: str, write_group_xmlid: str) -> nx.DiGraph:
    G = nx.DiGraph()
    G.add_node(f"model:{model_name}", node_type="Model", name=model_name)
    G.add_node(
        f"acl:{model_name}.access_manager",
        node_type="AccessEntry",
        perm_read=True, perm_write=True, perm_create=True, perm_unlink=True,
        all_authenticated=False,
    )
    G.add_node(f"group:{write_group_xmlid}", node_type="Group", name="Manager")
    G.add_edge(f"model:{model_name}", f"acl:{model_name}.access_manager", edge_type="GRANTED_BY")
    G.add_edge(f"acl:{model_name}.access_manager", f"group:{write_group_xmlid}", edge_type="APPLIES_TO_GROUP")
    return G


def test_raw_integer_group_id_never_matches_xmlid_graph():
    """
    Documents the bug as it exists without translation: a real manager,
    identified only by their database group ID (as the JWT actually
    provides), is NOT recognized as elevated -- even though they hold the
    real write group -- because the graph only knows the xml_id.
    """
    G = _build_graph_with_acl("account.move", "account.group_account_manager")
    # This is exactly what arrives from the JWT today: raw DB ids as strings.
    raw_jwt_group_ids_as_strings = ["42"]  # the manager's real group, id=42
    assert _has_elevated_access(G, "account.move", raw_jwt_group_ids_as_strings) is False


def test_resolved_xmlid_correctly_recognizes_elevated_access(monkeypatch):
    """
    Same scenario, but with the group ID resolved to its xml_id first
    (simulating _resolve_user_group_xmlids() called on the JWT's raw ID) --
    elevated access must now be correctly recognized.
    """
    G = _build_graph_with_acl("account.move", "account.group_account_manager")
    resolved_xmlids = ["account.group_account_manager"]  # id=42 resolved
    assert _has_elevated_access(G, "account.move", resolved_xmlids) is True

    gated_text, omitted = gate_observation(
        tool_name="analyser_verrous_securite",
        model_name="account.move",
        observation="Hardcoded validators: [admin@corp.com]",
        G=G,
        user_groups=resolved_xmlids,
    )
    assert omitted == []
    assert gated_text == "Hardcoded validators: [admin@corp.com]"


def test_resolve_user_group_xmlids_translates_via_rpc(monkeypatch):
    """
    Unit test of rag.graph._resolve_user_group_xmlids itself, mocking the
    RPC layer so no live Odoo instance is required. Verifies the JWT's raw
    integer group IDs get correctly turned into xml_ids before reaching
    gating/rule evaluation.
    """
    from rag import graph as graph_module

    class _FakeRpcClient:
        def authenticate_admin(self):
            return 1  # fake admin uid

        def get_group_xmlids(self, uid, group_ids):
            catalog = {42: "account.group_account_manager", 17: "base.group_user"}
            return {gid: catalog[gid] for gid in group_ids if gid in catalog}

    monkeypatch.setattr(
        "code_intelligence.odoo_rpc_client.OdooRpcClient",
        lambda: _FakeRpcClient(),
    )
    # Reset module-level singleton/cache so the monkeypatched client is used.
    # Use monkeypatch.setattr (not a bare assignment) so pytest restores the
    # ORIGINAL objects after this test -- a bare `graph_module._ADMIN_RPC_CLIENT
    # = None` would leave whatever THIS test assigns to it (a live
    # _FakeRpcClient instance, once _get_admin_rpc_client() re-populates it)
    # permanently in place for every test that runs afterwards in the same
    # pytest process, since monkeypatch only tracks attributes it set itself.
    # Confirmed to cause exactly this leak into
    # test_j25_26_e2e_purchase_bypass_gate.py (see conversation 2026-08-05).
    monkeypatch.setattr(graph_module, "_ADMIN_RPC_CLIENT", None)
    monkeypatch.setattr(graph_module, "_ADMIN_RPC_UID", None)
    monkeypatch.setattr(graph_module, "_GROUP_XMLID_CACHE", {})

    resolved = graph_module._resolve_user_group_xmlids([42, 17])
    assert set(resolved) == {"account.group_account_manager", "base.group_user"}


def test_resolve_user_group_xmlids_fails_closed_on_unresolvable_id(monkeypatch):
    """An ID with no matching ir.model.data entry (or an RPC error) must be
    dropped, never guessed -- fail closed, never fail open."""
    from rag import graph as graph_module

    class _FakeRpcClient:
        def authenticate_admin(self):
            return 1

        def get_group_xmlids(self, uid, group_ids):
            return {}  # nothing resolves

    monkeypatch.setattr(
        "code_intelligence.odoo_rpc_client.OdooRpcClient",
        lambda: _FakeRpcClient(),
    )
    monkeypatch.setattr(graph_module, "_ADMIN_RPC_CLIENT", None)
    monkeypatch.setattr(graph_module, "_ADMIN_RPC_UID", None)
    monkeypatch.setattr(graph_module, "_GROUP_XMLID_CACHE", {})

    assert graph_module._resolve_user_group_xmlids([999]) == []
