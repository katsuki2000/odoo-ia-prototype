#!/usr/bin/env python3
"""
scripts/fix_racine2_clean_test_no_group_2026.py

Root-cause fix -- todo/contexte.txt sections 256-258, Racine 2, option 1.

test_no_group_2026 a derive : il porte 17 groupes en base (RH, recrutement,
notes de frais...) au lieu du seul base.group_user attendu par son nom et par
l'intention des tests J5/J6 (code_intelligence/tests/test_j5_live_validation.py,
test_j6_context_validation.py). L'un de ces groupes en trop,
hr_expense.group_hr_expense_team_approver, accorde legitimement la lecture
sur account.move via une ACL STANDARD DU CORE ODOO
(hr_expense/security/ir.model.access.csv::access_account_move_user) --
d'ou le "DID NOT RAISE Fault" observe.

Ce script restaure test_no_group_2026 a son intention d'origine : uniquement
base.group_user, rien d'autre.

SECURITE : dry-run par defaut (affiche le plan, n'ecrit rien). Ecriture reelle
uniquement avec --apply, apres confirmation interactive explicite (tape
"oui").

Usage :
    python scripts/fix_racine2_clean_test_no_group_2026.py            # dry-run
    python scripts/fix_racine2_clean_test_no_group_2026.py --apply    # ecrit
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from code_intelligence.agent.rpc_client import OdooRpcClient

TARGET_LOGIN = "test_no_group_2026"
KEEP_XMLID = "base.group_user"
TEST_PASSWORD = os.getenv("ODOO_J5_TEST_PASSWORD", "J5TestPassword2026!")


def main() -> None:
    apply = "--apply" in sys.argv

    client = OdooRpcClient()
    admin_uid = client.authenticate_admin()
    print(f"[admin] uid={admin_uid} db={client.db} url={client.url}\n")

    users = client.execute_kw(
        admin_uid,
        "res.users",
        "search_read",
        [[("login", "=", TARGET_LOGIN)]],
        {"fields": ["id", "login", "groups_id"], "limit": 1},
    )
    if not users:
        print(f"ERREUR : utilisateur '{TARGET_LOGIN}' introuvable.")
        sys.exit(1)

    user_id = users[0]["id"]
    current_group_ids = set(users[0]["groups_id"])
    xmlids = client.get_group_xmlids(admin_uid, list(current_group_ids))

    keep_ids = client.resolve_xmlids_to_ids(admin_uid, [KEEP_XMLID])
    if KEEP_XMLID not in keep_ids:
        print(f"ERREUR : impossible de resoudre {KEEP_XMLID!r} sur cette instance.")
        sys.exit(1)
    keep_id = keep_ids[KEEP_XMLID]

    to_remove = sorted(current_group_ids - {keep_id})

    print(f"[cible] {TARGET_LOGIN} (id={user_id})")
    print(f"[etat actuel] {len(current_group_ids)} groupe(s) :")
    for gid in sorted(current_group_ids):
        marker = "  <-- CONSERVE" if gid == keep_id else "  <-- A RETIRER"
        print(f"    - {gid}: {xmlids.get(gid, '<pas de xml_id>')}{marker}")

    if not to_remove:
        print(f"\nRien a faire : {TARGET_LOGIN} ne porte deja que {KEEP_XMLID}.")
        return

    print(f"\n[plan] {len(to_remove)} groupe(s) a retirer, {KEEP_XMLID} (id={keep_id}) conserve seul.")

    if not apply:
        print("\nDRY-RUN -- aucune ecriture effectuee. Relancer avec --apply pour appliquer ce plan.")
        return

    print(f"\nConfirmation requise : ecrire groups_id=[{keep_id}] sur {TARGET_LOGIN} (id={user_id}).")
    answer = input("Taper 'oui' pour confirmer : ").strip().lower()
    if answer != "oui":
        print("Annule -- aucune ecriture effectuee.")
        return

    client.execute_kw(
        admin_uid,
        "res.users",
        "write",
        [[user_id], {"groups_id": [(6, 0, [keep_id])]}],
    )
    print("\n[ecrit] groups_id mis a jour.")

    # Verification immediate : relire l'utilisateur + rejouer le check qui echouait.
    reloaded = client.execute_kw(
        admin_uid,
        "res.users",
        "read",
        [[user_id]],
        {"fields": ["groups_id"]},
    )[0]
    print(f"[verif] groups_id apres ecriture : {reloaded['groups_id']}")
    assert reloaded["groups_id"] == [keep_id], "ecriture non conforme au plan -- a investiguer manuellement"

    import xmlrpc.client

    uid = client.authenticate_user(TARGET_LOGIN, TEST_PASSWORD)
    try:
        result = client.check_access_rights(uid, "account.move", "read")
        print(f"[verif] check_access_rights renvoie encore {result!r} -- BUG TOUJOURS PRESENT, a investiguer.")
    except xmlrpc.client.Fault as exc:
        print(f"[verif] Fault levee comme attendu : {exc.faultString}")
        print("[verif] Racine 2 resolue : le refus ACL est de retour pour ce compte.")


if __name__ == "__main__":
    main()
