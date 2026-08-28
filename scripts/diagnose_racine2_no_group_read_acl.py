#!/usr/bin/env python3
"""
scripts/diagnose_racine2_no_group_read_acl.py

Diagnostic script -- todo/contexte.txt section 256, Racine 2.

test_j5_live_validation.py::test_no_group_user_blocked_by_acl[read] et
test_j6_context_validation.py::test_q6_no_group_acl_denial_is_not_a_context_effect
echouent avec "DID NOT RAISE Fault" : test_no_group_2026 parvient a LIRE
account.move alors que l'ACL devrait le refuser (base.group_user seul,
aucun groupe comptable). Le cas write du meme test passe toujours (refus
confirme) -- seule la lecture est concernee.

3 hypotheses non tranchees par lecture de fichiers seule (voir section 256) :
  (a) l'ACL en base a derive du CSV source (module pas mis a jour, -u pas rejoue)
  (b) test_no_group_2026 porte reellement un groupe supplementaire en base
  (c) autre derive DB non visible depuis les fichiers seuls

Ce script est read-only vis-a-vis d'Odoo : aucune ecriture (pas de
res.users.write, pas de mise a jour de module) -- uniquement des
search_read/read/execute_kw en lecture, plus une reproduction directe du
check qui echoue dans J5/J6 (check_access_rights) pour voir le Fault (ou son
absence) en direct.
"""

import os
import sys
import xmlrpc.client
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from code_intelligence.odoo_rpc_client import OdooRpcClient  # noqa: E402

TEST_PASSWORD = os.getenv("ODOO_J5_TEST_PASSWORD", "J5TestPassword2026!")


def diagnose_groups(client: OdooRpcClient, admin_uid: int) -> None:
    print("=== (b) groups_id reels : test_no_group_2026 vs test_regional_2026 (reference) ===")
    for login in ("test_no_group_2026", "test_regional_2026"):
        users = client.execute_kw(
            admin_uid,
            "res.users",
            "search_read",
            [[("login", "=", login)]],
            {"fields": ["id", "login", "groups_id"], "limit": 1},
        )
        if not users:
            print(f"[groups] {login}: UTILISATEUR INTROUVABLE")
            continue
        group_ids = users[0]["groups_id"]
        xmlids = client.get_group_xmlids(admin_uid, group_ids)
        print(f"[groups] {login} (id={users[0]['id']}) : {len(group_ids)} groupe(s)")
        for gid in sorted(group_ids):
            print(f"    - {gid}: {xmlids.get(gid, '<pas de xml_id resoluble>')}")


def diagnose_acl(client: OdooRpcClient, admin_uid: int) -> None:
    print("\n=== (a) ir.model.access reels sur account.move (etat DB, pas le CSV source) ===")
    accesses = client.execute_kw(
        admin_uid,
        "ir.model.access",
        "search_read",
        [[("model_id.model", "=", "account.move")]],
        {"fields": ["name", "group_id", "perm_read", "perm_write", "perm_create", "perm_unlink", "active"]},
    )
    for acc in accesses:
        group_label = acc["group_id"][1] if acc["group_id"] else "(AUCUN GROUPE -- s'applique a tout le monde)"
        print(
            f"    - {acc['name']!r} group={group_label} "
            f"read={acc['perm_read']} write={acc['perm_write']} "
            f"create={acc['perm_create']} unlink={acc['perm_unlink']} active={acc['active']}"
        )


def diagnose_module_state(client: OdooRpcClient, admin_uid: int) -> None:
    print("\n=== (a) etat d'installation des modules concernes (derive -u ?) ===")
    modules = client.execute_kw(
        admin_uid,
        "ir.module.module",
        "search_read",
        [[("name", "in", ["account", "custom_credit_note_approval", "custom_credit_note_visibility_rules"])]],
        {"fields": ["name", "state", "latest_version", "installed_version", "write_date"]},
    )
    for mod in modules:
        print(
            f"    - {mod['name']}: state={mod['state']} "
            f"installed_version={mod.get('installed_version')} write_date={mod['write_date']}"
        )


def diagnose_direct_repro(client: OdooRpcClient) -> None:
    print("\n=== Reproduction directe du check qui echoue dans J5/J6 ===")
    uid = client.authenticate_user("test_no_group_2026", TEST_PASSWORD)
    print(f"[auth] test_no_group_2026 -> uid={uid}")
    try:
        result = client.check_access_rights(uid, "account.move", "read")
        print(f"    -> AUCUNE Fault levee. check_access_rights a renvoye : {result!r}")
        print("    -> BUG REPRODUIT ICI, en direct.")
    except xmlrpc.client.Fault as exc:
        print(f"    -> Fault levee comme attendu : {exc.faultString}")
        print("    -> PAS reproduit ici : le bug ne se manifeste pas sur ce run.")


def main() -> None:
    client = OdooRpcClient()
    admin_uid = client.authenticate_admin()
    print(f"[admin] uid={admin_uid} db={client.db} url={client.url}\n")

    diagnose_groups(client, admin_uid)
    diagnose_acl(client, admin_uid)
    diagnose_module_state(client, admin_uid)
    diagnose_direct_repro(client)


if __name__ == "__main__":
    main()
