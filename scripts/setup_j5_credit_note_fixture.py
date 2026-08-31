#!/usr/bin/env python3
"""
scripts/setup_j5_credit_note_fixture.py

Population idempotente de la donnee metier manquante pour
code_intelligence/tests/conftest.py::live_client (fixture partagee entre
test_j5_live_validation.py et test_j6_context_validation.py) :
un account.move (move_type='out_refund', amount_total >= 80000) que la
fixture cherche en base reelle avant de laisser tourner les 21 tests J5/J6.

Volontairement SEPARE de scripts/setup_j5_security_test_users.py (qui ne
cree que les 3 comptes utilisateurs) -- cf. todo/contexte.txt section 316 :
aucun script existant ne creait cette donnee, tools/full_setup.py ne cree
que des sale.order/factures standard, jamais d'avoir (out_refund).

Complication non triviale, documentee ici pour ne pas la re-decouvrir :
trois ir.rule s'appliquent en AND sur account.move pour test_regional_2026
et test_both_2026 (tous deux dans account.group_account_invoice) :

  1. rule_avoir_multi_societe (globale, sans groupe) :
     company_id = user.company_id.id

  2. rule_avoir_visibilite_departement (custom_credit_note_approval,
     attachee a account.group_account_invoice -- donc s'applique aux DEUX
     users test) : move_type != out_refund OR invoice_user_id = user.id
     OR journal_id.department_id = user.employee_id.department_id.id.
     Comme move_type = out_refund et que invoice_user_id ne peut valoir
     qu'UN seul des deux users a la fois, la seule branche exploitable
     pour que les DEUX users passent est le departement : le journal de
     l'avoir et l'employe de CHAQUE user doivent partager le meme
     hr.department.

  3. rule_avoir_visibilite_regionale / rule_avoir_visibilite_nationale
     (OR entre elles selon groupe -- deja couverte par les groupes poses
     par setup_j5_security_test_users.py).

D'ou la sequence : departement dedie -> lie aux DEUX employes (test_regional_2026,
test_both_2026) -> lie au journal de vente existant (reutilise celui de
tools/full_setup.py, pas de nouveau journal) -> avoir cree dessus.

test_no_group_2026 n'a pas besoin d'employe/departement : bloque en amont
par l'ACL (ir.model.access.csv restreint account.move a
account.group_account_invoice, qu'il n'a pas) -- la regle 2 ne le concerne
meme pas.

Mot de passe/connexion : meme OdooRpcClient que setup_j5_security_test_users.py,
aucune duplication.

Complication supplementaire decouverte a l'execution reelle (post section 318,
action_post de l'avoir echoue avec "Missing required account on accountable
line") : Company Alpha n'a JAMAIS eu de compte client (asset_receivable) --
tools/full_setup.py ne cree qu'un plan comptable minimal fait a la main (le
seul compte scope company_id=Alpha est 400000, revenu). Le compte "Account
Receivable" (121000) present sur 'Societe Dupont' appartient a une AUTRE
societe -- inutilisable pour la ligne contrepartie automatique que Odoo tente
de generer sous company_id=Alpha. Trou preexistant (pas cause par ce script),
jamais exerce avant parce que rien n'avait encore cree de facture/avoir
passant par la contrepartie auto de ce partenaire sous cette societe.

Fix : creation du compte 411000 (asset_receivable, company_id=Alpha, meme
schema que 400000) + pose de property_account_receivable_id sur 'Societe
Dupont'. Premiere tentative (voir todo/contexte.txt section 319) : ecrire
cette property comme Fiona (account.group_account_invoice), sur l'hypothese
que le scope societe d'une property ir.property suit le company_id de
l'utilisateur qui ecrit -- ECHEC REEL a l'execution (section 320) : Fiona
n'a aucun droit d'ecriture sur res.partner sur cette instance (Fault 4,
groupes requis -- Contact Creation, Inventory/Purchase/Sales Administrator,
Recruitment Officer -- aucun ne recoupe account.group_account_invoice).
Fix corrige : ecrire comme admin (qui a les droits) en forcant
explicitement le contexte `allowed_company_ids=[company_id]` sur l'appel --
c'est CE contexte qui determine self.env.company cote serveur (donc la
societe sur laquelle la property company-dependent est stockee), pas
l'identite ou le company_id par defaut de l'utilisateur qui ecrit. Le
compte 121000 existant pour l'autre societe reste intact -- aucun effet de
bord cross-societe.

Lecture seule vis-a-vis du code de production : ce script ne modifie aucun
fichier de code_intelligence/ ou odoo_addons/, uniquement l'etat de la base
Odoo live (hr.department, hr.employee, account.journal.department_id,
account.account, res.partner, account.move), au meme titre que
tools/full_setup.py.
"""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from code_intelligence.odoo_rpc_client import OdooRpcClient, OdooRpcError  # noqa: E402

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
