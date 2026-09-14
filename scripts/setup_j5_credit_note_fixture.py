#!/usr/bin/env python3
"""
Setup credit note fixture for J5/J6 live client tests.
Creates an account.move (move_type='out_refund', amount_total >= 80000)
with required accounts and department associations in Company Alpha.
"""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from code_intelligence.agent.rpc_client import OdooRpcClient, OdooRpcError

COMPANY_NAME = "Company Alpha"
DEPARTMENT_NAME = "Avoirs Test (J5/J6)"
SALES_JOURNAL_NAME = "Sales Journal (Company Alpha)"
INCOME_ACCOUNT_CODE = "400000"
CLIENT_NAME = "Société Dupont"
CREDIT_NOTE_REF = "AVOIR-J5-80K"
CREDIT_NOTE_AMOUNT = 85000  # > 80000 avec marge, mono-ligne

# Cf. docstring du module : Company Alpha n'a jamais eu de compte client.
# Meme schema que le compte revenu 400000 cree par tools/full_setup.py.
RECEIVABLE_ACCOUNT_CODE = "411000"
RECEIVABLE_ACCOUNT_NAME = "Clients (Company Alpha)"

TEST_USER_LOGINS = ("test_regional_2026", "test_both_2026")

# L'admin par defaut (login "admin") n'a aucun droit sur account.move sur
# cette instance -- "Administrator" general n'implique pas les groupes
# comptables (account.group_account_invoice/manager), qui se donnent par
# app separement. Plutot que d'ajouter artificiellement ces groupes a
# admin (effet de bord sur son profil de securite), la creation/lecture
# de l'avoir se fait avec Fiona Finance (fiona@alpha.com), deja creee par
# tools/full_setup.py avec account.group_account_invoice -- coherent avec
# le modele de securite Odoo (un comptable cree un avoir, pas le
# superadmin) et plus realiste pour le scenario de test.
FIONA_LOGIN = "fiona@alpha.com"
FIONA_PASSWORD = "password123"  # meme mot de passe que tools/full_setup.py::setup_users


def resolve_company_id(client: OdooRpcClient, admin_uid: int) -> int:
    ids = client.execute_kw(
        admin_uid, "res.company", "search", [[("name", "=", COMPANY_NAME)]], {"limit": 1}
    )
    if not ids:
        raise OdooRpcError(f"Company '{COMPANY_NAME}' not found -- run tools/full_setup.py first.")
    return int(ids[0])


def find_or_create_department(client: OdooRpcClient, admin_uid: int, company_id: int) -> int:
    ids = client.execute_kw(
        admin_uid, "hr.department", "search",
        [[("name", "=", DEPARTMENT_NAME), ("company_id", "=", company_id)]], {"limit": 1},
    )
    if ids:
        print(f"  -> Department '{DEPARTMENT_NAME}' already exists (ID: {ids[0]})")
        return int(ids[0])
    dept_id = client.execute_kw(
        admin_uid, "hr.department", "create",
        [{"name": DEPARTMENT_NAME, "company_id": company_id}],
    )
    print(f"  Created department '{DEPARTMENT_NAME}' (ID: {dept_id})")
    return int(dept_id)


def find_or_create_employee(client: OdooRpcClient, admin_uid: int, login: str,
                             department_id: int, company_id: int) -> None:
    user_ids = client.execute_kw(
        admin_uid, "res.users", "search", [[("login", "=", login)]], {"limit": 1}
    )
    if not user_ids:
        raise OdooRpcError(f"User '{login}' not found -- run scripts/setup_j5_security_test_users.py first.")
    user_id = int(user_ids[0])

    emp_ids = client.execute_kw(
        admin_uid, "hr.employee", "search", [[("user_id", "=", user_id)]], {"limit": 1}
    )
    if emp_ids:
        client.execute_kw(
            admin_uid, "hr.employee", "write",
            [[emp_ids[0]], {"department_id": department_id}],
        )
        print(f"  -> Updated employee for '{login}' (ID: {emp_ids[0]}), department set")
        return

    emp_id = client.execute_kw(
        admin_uid, "hr.employee", "create",
        [{
            "name": f"J5 Test ({login})",
            "user_id": user_id,
            "department_id": department_id,
            "company_id": company_id,
        }],
    )
    print(f"  Created employee for '{login}' (ID: {emp_id})")


def resolve_and_tag_journal(client: OdooRpcClient, admin_uid: int, department_id: int,
                             company_id: int) -> int:
    ids = client.execute_kw(
        admin_uid, "account.journal", "search",
        [[("name", "=", SALES_JOURNAL_NAME), ("company_id", "=", company_id)]], {"limit": 1},
    )
    if not ids:
        raise OdooRpcError(f"Journal '{SALES_JOURNAL_NAME}' not found -- run tools/full_setup.py first.")
    journal_id = int(ids[0])
    client.execute_kw(
        admin_uid, "account.journal", "write",
        [[journal_id], {"department_id": department_id}],
    )
    print(f"  -> Journal '{SALES_JOURNAL_NAME}' (ID: {journal_id}) tagged with department {department_id}")
    return journal_id


def resolve_income_account_id(client: OdooRpcClient, admin_uid: int, company_id: int) -> int:
    ids = client.execute_kw(
        admin_uid, "account.account", "search",
        [[("code", "=", INCOME_ACCOUNT_CODE), ("company_id", "=", company_id)]], {"limit": 1},
    )
    if not ids:
        raise OdooRpcError(f"Income account '{INCOME_ACCOUNT_CODE}' not found -- run tools/full_setup.py first.")
    return int(ids[0])


def find_or_create_receivable_account_id(client: OdooRpcClient, admin_uid: int, company_id: int) -> int:
    ids = client.execute_kw(
        admin_uid, "account.account", "search",
        [[("code", "=", RECEIVABLE_ACCOUNT_CODE), ("company_id", "=", company_id)]], {"limit": 1},
    )
    if ids:
        print(f"  -> Receivable account '{RECEIVABLE_ACCOUNT_CODE}' already exists (ID: {ids[0]})")
        return int(ids[0])
    account_id = client.execute_kw(
        admin_uid, "account.account", "create",
        [{
            "name": RECEIVABLE_ACCOUNT_NAME,
            "code": RECEIVABLE_ACCOUNT_CODE,
            "account_type": "asset_receivable",
            "company_id": company_id,
            "reconcile": True,
        }],
    )
    print(f"  Created receivable account '{RECEIVABLE_ACCOUNT_CODE}' for Company Alpha (ID: {account_id})")
    return int(account_id)


def set_partner_receivable_account(client: OdooRpcClient, admin_uid: int, company_id: int, partner_id: int, account_id: int) -> None:
    """Ecrit comme admin, PAS comme Fiona -- la premiere tentative (Fiona) a
    echoue reellement avec Fault 4 ("You are not allowed to modify
    'Contact'"): account.group_account_invoice ne couvre pas res.partner en
    ecriture sur cette instance. Le scope societe correct de cette property
    company-dependent (ir.property) n'est pas garanti par l'identite/
    company_id par defaut de l'utilisateur qui ecrit, mais par le contexte
    `allowed_company_ids` de l'appel -- c'est lui qui determine
    self.env.company cote serveur. Le forcer ici a [company_id] (Alpha)
    donne le meme resultat que l'ecriture-en-tant-que-Fiona visait, sans
    exiger de droits que l'utilisateur choisi n'a pas.
    """
    context = {"allowed_company_ids": [company_id]}
    partner = client.execute_kw(
        admin_uid, "res.partner", "read", [[partner_id]],
        {"fields": ["property_account_receivable_id"], "context": context},
    )
    current = partner[0]["property_account_receivable_id"]
    if current and current[0] == account_id:
        print(f"  -> '{CLIENT_NAME}' already has receivable account {account_id} set")
        return
    client.execute_kw(
        admin_uid, "res.partner", "write",
        [[partner_id], {"property_account_receivable_id": account_id}],
        {"context": context},
    )
    print(f"  -> Set property_account_receivable_id={account_id} on '{CLIENT_NAME}' (ecrit comme admin, contexte allowed_company_ids force a Alpha)")


def resolve_partner_id(client: OdooRpcClient, admin_uid: int) -> int:
    ids = client.execute_kw(
        admin_uid, "res.partner", "search", [[("name", "=", CLIENT_NAME)]], {"limit": 1}
    )
    if not ids:
        raise OdooRpcError(f"Client '{CLIENT_NAME}' not found -- run tools/full_setup.py first.")
    return int(ids[0])


def find_or_create_credit_note(client: OdooRpcClient, fiona_uid: int, company_id: int,
                                journal_id: int, partner_id: int, income_account_id: int) -> int:
    """Runs entirely as Fiona Finance (account.group_account_invoice), never
    as admin -- see FIONA_LOGIN/FIONA_PASSWORD comment above for why. Every
    execute_kw call below passes fiona_uid explicitly; OdooRpcClient caches
    one password per uid internally (_password_by_uid), so this does not
    mutate or affect the admin_uid session used by the rest of this script.
    """
    ids = client.execute_kw(
        fiona_uid, "account.move", "search",
        [[("ref", "=", CREDIT_NOTE_REF), ("move_type", "=", "out_refund")]], {"limit": 1},
    )
    if ids:
        move_id = int(ids[0])
        print(f"  -> Credit note '{CREDIT_NOTE_REF}' already exists (ID: {move_id})")
        return move_id

    move_vals = {
        "move_type": "out_refund",
        "ref": CREDIT_NOTE_REF,
        "partner_id": partner_id,
        "company_id": company_id,
        "journal_id": journal_id,
        "invoice_line_ids": [(0, 0, {
            "name": "Avoir de test J5/J6 (fixture 80k)",
            "quantity": 1,
            "price_unit": CREDIT_NOTE_AMOUNT,
            "account_id": income_account_id,
        })],
    }
    move_id = client.execute_kw(fiona_uid, "account.move", "create", [move_vals])
    print(f"  Created credit note '{CREDIT_NOTE_REF}' (ID: {move_id}), amount_total target={CREDIT_NOTE_AMOUNT}")

    try:
        client.execute_kw(fiona_uid, "account.move", "action_post", [[move_id]])
        print(f"    -> Posted (state=posted)")
    except Exception as e:
        print(f"    Warning: could not post credit note (left as draft): {e}")

    return move_id


def main() -> None:
    print("Setup J5/J6 credit note fixture (80k+ out_refund on account.move)")
    print("=" * 90)

    client = OdooRpcClient()
    admin_uid = client.authenticate_admin()
    print(f"Authenticated as admin (UID: {admin_uid})")

    company_id = resolve_company_id(client, admin_uid)
    print(f"Company '{COMPANY_NAME}' ID: {company_id}")

    department_id = find_or_create_department(client, admin_uid, company_id)

    for login in TEST_USER_LOGINS:
        find_or_create_employee(client, admin_uid, login, department_id, company_id)

    journal_id = resolve_and_tag_journal(client, admin_uid, department_id, company_id)
    income_account_id = resolve_income_account_id(client, admin_uid, company_id)
    partner_id = resolve_partner_id(client, admin_uid)

    receivable_account_id = find_or_create_receivable_account_id(client, admin_uid, company_id)
    set_partner_receivable_account(client, admin_uid, company_id, partner_id, receivable_account_id)

    fiona_uid = client.authenticate_user(FIONA_LOGIN, FIONA_PASSWORD)
    print(f"Authenticated as Fiona Finance for the credit note itself (UID: {fiona_uid})")

    move_id = find_or_create_credit_note(
        client, fiona_uid, company_id, journal_id, partner_id, income_account_id
    )

    read = client.execute_kw(
        fiona_uid, "account.move", "read", [[move_id]],
        {"fields": ["amount_total", "move_type", "state", "company_id"]},
    )
    print(f"\nFinal state: {read}")

    print("\n" + "=" * 90)
    print("Done. Rerun `pytest code_intelligence/tests/ -v` (or -m integration) to confirm J5/J6 pass.")


if __name__ == "__main__":
    main()
