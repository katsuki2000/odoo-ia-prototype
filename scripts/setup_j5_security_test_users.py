#!/usr/bin/env python3
"""
scripts/setup_j5_security_test_users.py

Population idempotente des 3 comptes de test de securite requis par
code_intelligence/tests/conftest.py::live_client (fixture partagee entre
test_j5_live_validation.py et test_j6_context_validation.py) :

    test_no_group_2026, test_regional_2026, test_both_2026

Volontairement SEPARE de tools/full_setup.py (donnees de demo metier :
societe, clients, produits, commandes de vente, tickets) et de
scripts/create_manager.py (utilisateur manager unique) -- ces 3 comptes
n'ont pas de rapport avec la donnee de demo, leur seule raison d'etre est
de porter une combinaison precise de groupes de securite pour exercer les
regles ACL / ir.rule sur account.move dans J5/J6. Coupler les cycles de
vie reviendrait a devoir toucher un script de demo generale a chaque
evolution des tests de securite (et inversement).

Specification des groupes -- reconstituee par lecture directe des modules
sur disque (PAS supposee) :

  - security/ir.model.access.csv (custom_credit_note_approval) :
    account.move n'est lisible/ecrivable QUE par le groupe
    account.group_account_invoice ("Billing") -- sans ce groupe, l'ACL
    refuse tout acces avant meme l'evaluation d'un ir.rule.
  - security/security_groups.xml (custom_credit_note_visibility_rules) :
    definit group_avoir_regional ("Avoirs - Visibilite Regionale") et
    group_avoir_national ("Avoirs - Visibilite Nationale").
  - security/ir_rule_layered.xml (custom_credit_note_visibility_rules) :
    regle regionale plafonnee a 50000e (group_avoir_regional), regle
    nationale illimitee (group_avoir_national) -- combinees en OR entre
    elles pour un meme requeteur, comme documente dans
    scripts/check_bloc9_02_credit_note_visibility_e2e.py ("Q6.1 = member
    of BOTH groups").

D'ou la table :

  test_no_group_2026  : base.group_user SEUL
                         -> refuse par l'ACL (ni Billing, ni groupe avoir)
  test_regional_2026   : base.group_user + account.group_account_invoice
                         + group_avoir_regional
                         -> plafond regional 50k, mais OR-combine avec la
                            regle departementale du groupe Billing
  test_both_2026       : base.group_user + account.group_account_invoice
                         + group_avoir_regional + group_avoir_national
                         -> "both" = membre des DEUX groupes avoirs
                            (regional ET national), pas Billing+national

Mot de passe : ODOO_J5_TEST_PASSWORD (meme variable d'env que
code_intelligence/tests/conftest.py), defaut J5TestPassword2026! --
partage intentionnellement pour que la fixture live_client (qui appelle
set_user_password a chaque run) et ce script de population restent
coherents sans duplication de constante.

Lecture seule vis-a-vis du code de production : ce script ne modifie
aucun fichier de code_intelligence/ ou core/, uniquement l'etat de la
base Odoo live (creation/mise a jour de res.users), au meme titre que
tools/full_setup.py ou scripts/create_manager.py.
"""

import os
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from code_intelligence.live.rpc_client import OdooRpcClient, OdooRpcError  # noqa: E402

TEST_PASSWORD = os.getenv("ODOO_J5_TEST_PASSWORD", "J5TestPassword2026!")
COMPANY_NAME = "Company Alpha"

GROUP_XMLIDS = {
    "base_user": "base.group_user",
    "billing": "account.group_account_invoice",
    "avoir_regional": "custom_credit_note_visibility_rules.group_avoir_regional",
    "avoir_national": "custom_credit_note_visibility_rules.group_avoir_national",
}

# login -> cle logique des groupes requis (voir GROUP_XMLIDS)
TEST_USERS_SPEC = {
    "test_no_group_2026": ["base_user"],
    "test_regional_2026": ["base_user", "billing", "avoir_regional"],
    "test_both_2026": ["base_user", "billing", "avoir_regional", "avoir_national"],
}


def resolve_company_id(client: OdooRpcClient, admin_uid: int) -> int:
    company_ids = client.execute_kw(
        admin_uid, "res.company", "search", [[("name", "=", COMPANY_NAME)]], {"limit": 1}
    )
    if not company_ids:
        raise OdooRpcError(
            f"Company '{COMPANY_NAME}' not found -- run tools/full_setup.py first "
            f"(Step 1: Company, Sales Journal & Income Account)."
        )
    return int(company_ids[0])


def resolve_group_ids(client: OdooRpcClient, admin_uid: int) -> dict:
    xmlid_to_id = client.resolve_xmlids_to_ids(admin_uid, list(GROUP_XMLIDS.values()))
    resolved = {}
    missing = []
    for key, xmlid in GROUP_XMLIDS.items():
        if xmlid in xmlid_to_id:
            resolved[key] = xmlid_to_id[xmlid]
        else:
            missing.append(xmlid)
    if missing:
        raise OdooRpcError(
            "Could not resolve required group xml_id(s): "
            f"{missing} -- required modules "
            "(custom_credit_note_approval, custom_credit_note_visibility_rules) "
            "may not be installed on this instance."
        )
    return resolved


def setup_user(client: OdooRpcClient, admin_uid: int, login: str, group_keys: list,
                group_ids_by_key: dict, company_id: int) -> None:
    group_ids = sorted({group_ids_by_key[key] for key in group_keys})
    existing_ids = client.execute_kw(
        admin_uid, "res.users", "search", [[("login", "=", login)]], {"limit": 1}
    )

    if existing_ids:
        user_id = int(existing_ids[0])
        client.execute_kw(
            admin_uid, "res.users", "write",
            [[user_id], {
                "password": TEST_PASSWORD,
                "groups_id": [(6, 0, group_ids)],
                "company_id": company_id,
                "company_ids": [(6, 0, [company_id])],
            }],
        )
        print(f"  -> Updated existing user '{login}' (ID: {user_id}), groups reset to {group_keys}")
        return

    user_vals = {
        "name": f"J5 Test ({login})",
        "login": login,
        "password": TEST_PASSWORD,
        "company_id": company_id,
        "company_ids": [(6, 0, [company_id])],
        "groups_id": [(6, 0, group_ids)],
    }
    user_id = client.execute_kw(admin_uid, "res.users", "create", [user_vals])
    print(f"  Created user '{login}' (ID: {user_id}), groups = {group_keys}")


def main() -> None:
    print("Setup J5/J6 security test users (test_no_group_2026, test_regional_2026, test_both_2026)")
    print("=" * 90)

    client = OdooRpcClient()
    admin_uid = client.authenticate_admin()
    print(f"Authenticated as admin (UID: {admin_uid})")

    company_id = resolve_company_id(client, admin_uid)
    print(f"Company '{COMPANY_NAME}' ID: {company_id}")

    group_ids_by_key = resolve_group_ids(client, admin_uid)
    print(f"Resolved group IDs: {group_ids_by_key}")

    for login, group_keys in TEST_USERS_SPEC.items():
        setup_user(client, admin_uid, login, group_keys, group_ids_by_key, company_id)

    print("\n" + "=" * 90)
    print("Done. Rerun `pytest code_intelligence/tests/ -v` (or -m integration) to confirm J5/J6 pass.")


if __name__ == "__main__":
    main()
