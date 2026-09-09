#!/usr/bin/env python3
"""
scripts/single_company_cleanup.py

Root-cause fix pour todo/contexte.txt section 321 : Company Alpha ne devrait
jamais avoir coexiste avec 'My Company' (societe demo par defaut d'Odoo,
company_id=1) -- decision explicite de l'utilisateur : une seule societe
active par instance (miroir du modele "un ERP par societe" en production).

Root cause du blocage J5/J6 (contexte.txt section 321) : rule_avoir_multi_societe
compare account.move.company_id au champ STOCKE res.users.company_id de
l'utilisateur qui lit -- pas au contexte RPC allowed_company_ids. L'admin avait
company_id=1 (My Company) alors que l'avoir de test vit sous company_id=2
(Alpha), d'ou le filtrage silencieux (confirme empiriquement : search() en
admin renvoie [] meme avec allowed_company_ids=[2] force ; search() en Fiona,
dont company_id=2 par defaut, trouve l'avoir immediatement). Fix a la racine :
faire disparaitre 'My Company' plutot que contourner via un autre utilisateur
dans le code de test -- pas de multi-societe voulu ici.

Idempotent : si 'My Company' est deja absente/archivee, ce script ne fait
rien (safe a re-executer sur chaque machine).

Inventaire pre-migration (todo/contexte.txt section 321) : seul l'admin
(uid=2) avait company_id=1 par defaut et 1 dans company_ids. Aucune donnee
metier (account.move, product.template) scopee a company_id=1 -- uniquement
le squelette demo standard d'une install Odoo neuve (47 comptes, 8 journaux,
1 partner, 1 departement/employe demo, 1 entrepot).
"""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from code_intelligence.live.rpc_client import OdooRpcClient, OdooRpcError  # noqa: E402

OLD_COMPANY_NAME = "My Company"
NEW_DEFAULT_COMPANY_NAME = "Company Alpha"


def main() -> None:
    print("Single-company cleanup: retire 'My Company', Company Alpha devient seule societe active")
    print("=" * 90)

    client = OdooRpcClient()
    admin_uid = client.authenticate_admin()
    print(f"Authenticated as admin (UID: {admin_uid})")

    old_ids = client.execute_kw(
        admin_uid, "res.company", "search",
        [[("name", "=", OLD_COMPANY_NAME)]], {"limit": 1},
    )
    if not old_ids:
        print(f"  -> '{OLD_COMPANY_NAME}' not found -- already removed, nothing to do.")
        return
    old_id = int(old_ids[0])

    new_ids = client.execute_kw(
        admin_uid, "res.company", "search",
        [[("name", "=", NEW_DEFAULT_COMPANY_NAME)]], {"limit": 1},
    )
    if not new_ids:
        raise OdooRpcError(f"'{NEW_DEFAULT_COMPANY_NAME}' not found -- run tools/full_setup.py first.")
    new_id = int(new_ids[0])

    # Reassign every user still defaulted to / scoped on the old company -- y compris les
    # users INACTIFS (context active_test=False) : le premier essai de unlink() a echoue sur
    # res_users_company_id_fkey a cause d'un user systeme archive (probablement OdooBot) que
    # la recherche par defaut (active=True implicite) ne voyait pas.
    stray_user_ids = client.execute_kw(
        admin_uid, "res.users", "search",
        [["|", ("company_id", "=", old_id), ("company_ids", "in", [old_id])]],
        {"context": {"active_test": False}},
    )
    # Defer updating the admin user (uid=2) until the very end so it doesn't lose access
    # to other users in company 1 before they are migrated.
    stray_user_ids = sorted(stray_user_ids, key=lambda u: u == admin_uid)
    
    for uid in stray_user_ids:
        user = client.execute_kw(
            admin_uid, "res.users", "read", [[uid]],
            {"fields": ["login", "company_id", "company_ids"], "context": {"active_test": False}},
        )[0]
        new_company_ids = sorted(set(cid for cid in user["company_ids"] if cid != old_id) | {new_id})
        client.execute_kw(
            admin_uid, "res.users", "write",
            [[uid], {"company_id": new_id, "company_ids": [(6, 0, new_company_ids)]}],
            {"context": {"active_test": False}},
        )
        print(f"  -> Reassigned user '{user['login']}' (ID: {uid}): company_id={new_id}, company_ids={new_company_ids}")

    # 'website' n'a pas de champ company_id-scope au meme sens que les autres modeles ci-dessus,
    # mais Odoo refuse d'archiver une societe tant qu'un site actif y pointe ("My Website",
    # confirme empiriquement -- Fault 2 rencontre a l'execution). Reassigne plutot que de toucher
    # au site lui-meme (non destructif).
    try:
        website_ids = client.execute_kw(
            admin_uid, "website", "search", [[("company_id", "=", old_id)]],
        )
        for website_id in website_ids:
            client.execute_kw(
                admin_uid, "website", "write", [[website_id], {"company_id": new_id}],
            )
            print(f"  -> Reassigned website (ID: {website_id}) to company_id={new_id}")
    except Exception as e:
        if "doesn't exist" in str(e):
            print("  -> Website module not installed, skipping website reassignment.")
        else:
            raise

    # Delete reel non tente : 47 comptes + 8 journaux + l'entrepot demo sont aussi scopes sur
    # company_id=1 (todo/contexte.txt section 321), chacun avec sa propre contrainte FK
    # restrict -- l'archivage (active=False) est la voie native Odoo pour retirer une societe
    # sans devoir reassigner/detruire tout son plan comptable demo.
    client.execute_kw(admin_uid, "res.company", "write", [[old_id], {"active": False}])
    print(f"  Archived '{OLD_COMPANY_NAME}' (ID: {old_id}, active=False).")

    print("\n" + "=" * 90)
    print("Done. Rerun the diagnostic (res.company search_read) to confirm final state.")


if __name__ == "__main__":
    main()
