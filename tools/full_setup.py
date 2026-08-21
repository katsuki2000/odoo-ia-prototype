#!/usr/bin/env python3
"""
tools/full_setup.py

Consolidated single setup script to populate a fresh Odoo 17 database (SINGLE COMPANY):
1. Single Company (Company Alpha) + Sales Journal + Income Account
2. 6 Specialized users + 1 Miro Manager user, all linked to Company Alpha
3. Clients (res.partner), products (product.template), sales orders (sales.json), tickets (tickets.json)

Architecture note: Multi-company (multiple res.company records in one single database)
was intentionally simplified. At MiroKE, each client company integrated with Odoo has its
OWN isolated Odoo database. Multi-tenant behavior will be tested via multiple distinct
databases rather than multiple res.company records in one DB.

Includes fixes for:
- Sales journal creation (account.journal type sale)
- Income account creation (account.account code 400000) and product category assignment
- Sales order cancellation for 'annul' status
- Task partner_id resolution for support tickets
"""

import xmlrpc.client
import json
import sys
import os

URL = "http://localhost:8069"
DB = "odoo-dev"
USERNAME = "admin"
PASSWORDS_TO_TRY = ["admin", "odoo"]

FAKE_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "document_rag/fake_data")


# --- Connection ---

def get_connection():
    common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
    uid = None
    password = None
    for pwd in PASSWORDS_TO_TRY:
        try:
            uid = common.authenticate(DB, USERNAME, pwd, {})
            if uid:
                password = pwd
                break
        except Exception:
            continue
    if not uid:
        print("Failed to authenticate with Odoo. Check credentials or DB name.")
        sys.exit(1)
    print(f"Authenticated as admin (UID: {uid})")
    models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")
    return uid, password, models


# --- Generic Helpers ---

def find_or_create(models, uid, pwd, model, search_domain, create_vals, label="record"):
    ids = models.execute_kw(DB, uid, pwd, model, 'search', [search_domain])
    if ids:
        print(f"  -> {label} already exists (ID: {ids[0]})")
        return ids[0]
    new_id = models.execute_kw(DB, uid, pwd, model, 'create', [create_vals])
    print(f"  Created {label} (ID: {new_id})")
    return new_id


def get_group_id(models, uid, pwd, xml_id):
    if "." not in xml_id:
        return None
    module, name = xml_id.split(".", 1)
    res = models.execute_kw(DB, uid, pwd, 'ir.model.data', 'search_read',
                            [[('module', '=', module), ('name', '=', name)]],
                            {'fields': ['res_id']})
    return res[0]['res_id'] if res else None


# --- Step 1: Single Company + Sales Journal + Income Account ---

def setup_company_and_journal(models, uid, pwd):
    print("\n--- Step 1: Company, Sales Journal & Income Account ---")

    alpha_id = find_or_create(models, uid, pwd, 'res.company',
                               [('name', '=', 'Company Alpha')],
                               {'name': 'Company Alpha'}, label="Company 'Company Alpha'")

    # Sales Journal
    journal_ids = models.execute_kw(
        DB, uid, pwd, 'account.journal', 'search',
        [[('type', '=', 'sale'), ('company_id', '=', alpha_id)]]
    )
    if not journal_ids:
        models.execute_kw(DB, uid, pwd, 'account.journal', 'create', [{
            'name': 'Sales Journal (Company Alpha)',
            'type': 'sale',
            'code': 'SJA',
            'company_id': alpha_id,
        }])
        print("  Created Sales Journal for Company Alpha (code: SJA)")
    else:
        print("  -> Sales Journal already exists for Company Alpha")

    # Income Account for Invoicing
    account_ids = models.execute_kw(
        DB, uid, pwd, 'account.account', 'search',
        [[('code', '=', '400000'), ('company_id', '=', alpha_id)]]
    )
    if not account_ids:
        income_account_id = models.execute_kw(DB, uid, pwd, 'account.account', 'create', [{
            'name': 'Ventes de marchandises / Services',
            'code': '400000',
            'account_type': 'income',
            'company_id': alpha_id,
        }])
        print("  Created Income Account 400000 for Company Alpha")
    else:
        income_account_id = account_ids[0]

    categ_ids = models.execute_kw(DB, uid, pwd, 'product.category', 'search', [[]])
    if categ_ids:
        try:
            models.execute_kw(DB, uid, pwd, 'product.category', 'write', [
                [categ_ids[0]],
                {'property_account_income_categ_id': income_account_id}
            ])
            print("  Assigned Income Account to Product Category")
        except Exception as e:
            print(f"  Warning: Could not assign income account to category: {e}")

    return alpha_id


# --- Step 2: Specialized Users (All on Company Alpha) ---

def setup_users(models, uid, pwd, alpha_id):
    print("\n--- Step 2: Specialized Users (all on Company Alpha) ---")
    internal_user_group = get_group_id(models, uid, pwd, "base.group_user")

    users_data = [
        {"name": "Alice Admin", "login": "alice@alpha.com",
         "groups": ["base.group_user", "sales_team.group_sale_manager", "project.group_project_manager"]},
        {"name": "Bob Buyer", "login": "bob@alpha.com",
         "groups": ["base.group_user", "purchase.group_purchase_manager", "stock.group_stock_manager"]},
        {"name": "Charlie CRM", "login": "charlie@alpha.com",
         "groups": ["base.group_user", "sales_team.group_sale_salesman"]},
        {"name": "Diana Support", "login": "diana@alpha.com",
         "groups": ["base.group_user", "project.group_project_user"]},
        {"name": "Evan Engineer", "login": "evan@alpha.com",
         "groups": ["base.group_user", "project.group_project_user", "stock.group_stock_user"]},
        {"name": "Fiona Finance", "login": "fiona@alpha.com",
         "groups": ["base.group_user", "account.group_account_invoice"]},
        {"name": "Miro Manager", "login": "manager@miro.com",
         "groups": ["base.group_user", "base.group_erp_manager",
                    "sales_team.group_sale_manager", "project.group_project_manager",
                    "stock.group_stock_manager", "account.group_account_manager"]},
    ]

    user_uids = {}
    for u in users_data:
        existing = models.execute_kw(DB, uid, pwd, 'res.users', 'search', [[('login', '=', u['login'])]])
        if existing:
            print(f"  -> User '{u['name']}' already exists (ID: {existing[0]})")
            user_uids[u['name']] = existing[0]
            continue

        group_ids = []
        for xml_id in u['groups']:
            gid = get_group_id(models, uid, pwd, xml_id)
            if gid and gid not in group_ids:
                group_ids.append(gid)
        if internal_user_group and internal_user_group not in group_ids:
            group_ids.append(internal_user_group)

        user_vals = {
            'name': u['name'],
            'login': u['login'],
            'password': 'password123',
            'company_id': alpha_id,
            'company_ids': [(6, 0, [alpha_id])],
        }
        if group_ids:
            user_vals['groups_id'] = [(6, 0, group_ids)]

        try:
            new_id = models.execute_kw(DB, uid, pwd, 'res.users', 'create', [user_vals])
            print(f"  Created User '{u['name']}' ({u['login']}) (ID: {new_id})")
            user_uids[u['name']] = new_id
        except Exception as e:
            print(f"  Warning: Could not create user '{u['name']}': {e}")

    return user_uids


# --- Step 3: Clients (All assigned to Company Alpha) ---

def setup_clients(models, uid, pwd, alpha_id):
    print("\n--- Step 3: Creating Clients ---")
    clients = {
        "Société Dupont": {"name": "Société Dupont", "company_type": "company",
                           "email": "contact@dupont.mg", "phone": "+261 20 22 123 45", "company_id": alpha_id},
        "Madagascar Tech": {"name": "Madagascar Tech", "company_type": "company",
                            "email": "info@madatech.mg", "phone": "+261 20 22 678 90", "company_id": alpha_id},
        "MIRO KE interne": {"name": "MIRO KE interne", "company_type": "company",
                            "email": "support@miroke.mg", "phone": "+261 20 22 000 00", "company_id": alpha_id},
        "Telma Madagascar": {"name": "Telma Madagascar", "company_type": "company",
                             "email": "contact@telma.mg", "phone": "+261 20 23 100 00", "company_id": alpha_id},
        "Groupe Socimex": {"name": "Groupe Socimex", "company_type": "company",
                           "email": "info@socimex.mg", "phone": "+261 20 22 345 67", "company_id": alpha_id},
        "Brasseries Star": {"name": "Brasseries Star", "company_type": "company",
                            "email": "contact@star.mg", "phone": "+261 20 22 456 78", "company_id": alpha_id},
        "Air Madagascar": {"name": "Air Madagascar", "company_type": "company",
                           "email": "commercial@airmadagascar.mg", "phone": "+261 20 22 222 22", "company_id": alpha_id},
        "Shoprite Madagascar": {"name": "Shoprite Madagascar", "company_type": "company",
                                "email": "procurement@shoprite.mg", "phone": "+261 20 22 567 89", "company_id": alpha_id},
    }
    client_ids = {}
    for name, vals in clients.items():
        cid = find_or_create(models, uid, pwd, 'res.partner',
                             [('name', '=', name)], vals, label=f"Client '{name}'")
        client_ids[name] = cid
    return client_ids


# --- Step 4: Products ---

def setup_products(models, uid, pwd):
    print("\n--- Step 4: Creating Products ---")
    products_data = [
        {"name": "Implémentation Odoo 17", "list_price": 4500000, "type": "service", "invoice_policy": "order",
         "description_sale": "Service complet d'implémentation Odoo 17 incluant configuration, migration et formation."},
        {"name": "Formation Odoo 17", "list_price": 1200000, "type": "service", "invoice_policy": "order",
         "description_sale": "Programme de formation Odoo 17 pour les utilisateurs et administrateurs."},
        {"name": "Support mensuel", "list_price": 800000, "type": "service", "invoice_policy": "order",
         "description_sale": "Contrat de support mensuel incluant maintenance, correctifs et assistance technique."},
        {"name": "Audit ERP", "list_price": 2800000, "type": "service", "invoice_policy": "order",
         "description_sale": "Audit complet de l'infrastructure ERP existante avec recommandations d'amélioration."},
        {"name": "Migration Odoo 16 vers 17", "list_price": 5600000, "type": "service", "invoice_policy": "order",
         "description_sale": "Migration complète d'Odoo 16 vers 17 incluant données, personnalisations et tests."},
        {"name": "Développement module sur mesure", "list_price": 3400000, "type": "service", "invoice_policy": "order",
         "description_sale": "Développement de modules Odoo personnalisés selon cahier des charges client."},
        {"name": "Maintenance annuelle", "list_price": 6000000, "type": "service", "invoice_policy": "order",
         "description_sale": "Contrat de maintenance annuelle couvrant mises à jour, correctifs et support prioritaire."},
        {"name": "Hébergement Cloud Odoo", "list_price": 960000, "type": "service", "invoice_policy": "order",
         "description_sale": "Hébergement cloud haute disponibilité pour instance Odoo avec sauvegardes quotidiennes."},
        {"name": "Intégration API tierce", "list_price": 3800000, "type": "service", "invoice_policy": "order",
         "description_sale": "Intégration d'APIs tierces (paiement, logistique, CRM) avec l'instance Odoo du client."},
        {"name": "Consulting stratégique IT", "list_price": 2200000, "type": "service", "invoice_policy": "order",
         "description_sale": "Conseil stratégique en transformation digitale et optimisation des processus IT."},
    ]
    product_ids = {}
    for p in products_data:
        pid = find_or_create(models, uid, pwd, 'product.template',
                             [('name', '=', p['name'])], p, label=f"Product '{p['name']}'")
        pp_ids = models.execute_kw(DB, uid, pwd, 'product.product', 'search',
                                   [[('product_tmpl_id', '=', pid)]])
        product_ids[p['name']] = pp_ids[0] if pp_ids else pid
    return product_ids


# --- Step 5: Sales Orders ---

def setup_sales_orders(models, uid, pwd, alpha_id, client_ids, product_ids, charlie_uid):
    print("\n--- Step 5: Creating Sales Orders ---")
    sales_file = os.path.join(FAKE_DATA_DIR, "sales.json")
    with open(sales_file, 'r', encoding='utf-8') as f:
        sales_data = json.load(f)

    for sale in sales_data:
        so_name = f"SO-MIRO-{sale['id']:04d}"
        existing = models.execute_kw(DB, uid, pwd, 'sale.order', 'search',
                                     [[('client_order_ref', '=', so_name)]])
        if existing:
            print(f"  -> Sale Order '{so_name}' already exists (ID: {existing[0]})")
            continue

        partner_id = client_ids.get(sale['client'])
        product_id = product_ids.get(sale['produit'])
        if not partner_id or not product_id:
            print(f"  Warning: Skipping SO {so_name} due to missing partner or product")
            continue

        so_vals = {
            'partner_id': partner_id,
            'date_order': sale['date'],
            'client_order_ref': so_name,
            'company_id': alpha_id,
            'user_id': charlie_uid or uid,
            'order_line': [(0, 0, {
                'product_id': product_id,
                'product_uom_qty': 1,
                'price_unit': sale['montant'],
                'name': sale['produit'],
            })],
        }

        try:
            so_id = models.execute_kw(DB, uid, pwd, 'sale.order', 'create', [so_vals])
            print(f"  Created Sale Order '{so_name}' (ID: {so_id}) - {sale['client']} / {sale['produit']} / {sale['montant']:,} Ar")

            if sale.get('statut') == 'facturé':
                try:
                    models.execute_kw(DB, uid, pwd, 'sale.order', 'action_confirm', [[so_id]])
                    # Re-write date_order because action_confirm overwrites date_order with current timestamp
                    dt_val = sale['date'] + " 10:00:00" if len(sale['date']) == 10 else sale['date']
                    models.execute_kw(DB, uid, pwd, 'sale.order', 'write', [[so_id], {'date_order': dt_val}])
                    print(f"    Confirmed SO {so_name}")
                    try:
                        context = {'active_model': 'sale.order', 'active_ids': [so_id], 'active_id': so_id}
                        wizard_id = models.execute_kw(DB, uid, pwd, 'sale.advance.payment.inv', 'create', [{}], {'context': context})
                        try:
                            models.execute_kw(DB, uid, pwd, 'sale.advance.payment.inv', 'create_invoices', [[wizard_id]], {'context': context})
                        except xmlrpc.client.Fault as e:
                            if "cannot marshal None" not in str(e):
                                raise

                        so_data = models.execute_kw(DB, uid, pwd, 'sale.order', 'read', [[so_id]], {'fields': ['invoice_ids']})
                        inv_ids = so_data[0]['invoice_ids']
                        if inv_ids:
                            models.execute_kw(DB, uid, pwd, 'account.move', 'action_post', [inv_ids])
                            print(f"      -> Invoiced & Posted (Invoice IDs: {inv_ids})")
                    except Exception as inv_err:
                        print(f"      -> Invoicing failed: {inv_err}")
                except Exception as e:
                    print(f"    Warning: Could not confirm/invoice SO {so_name}: {e}")
            elif sale.get('statut') == 'annulé':
                try:
                    models.execute_kw(DB, uid, pwd, 'sale.order', 'action_cancel', [[so_id]])
                    print(f"    Cancelled SO {so_name}")
                except Exception as e:
                    print(f"    Warning: Could not cancel SO {so_name}: {e}")
        except Exception as e:
            print(f"  Warning: Could not create SO {so_name}: {e}")


# --- Step 6: Support Project & Tickets ---

def setup_tickets(models, uid, pwd, alpha_id, client_ids, diana_uid, evan_uid):
    print("\n--- Step 6: Creating Support Project & Tasks ---")
    project_id = find_or_create(models, uid, pwd, 'project.project',
                                [('name', '=', 'MIRO Support Tickets')],
                                {'name': 'MIRO Support Tickets',
                                 'company_id': alpha_id,
                                 'user_id': evan_uid or uid,
                                 'description': 'Tickets de support technique internes et clients'},
                                label="Project 'MIRO Support Tickets'")

    tickets_file = os.path.join(FAKE_DATA_DIR, "tickets.json")
    with open(tickets_file, 'r', encoding='utf-8') as f:
        tickets_data = json.load(f)

    assignees = [a for a in [diana_uid, evan_uid] if a]

    for i, ticket in enumerate(tickets_data):
        task_name = f"[TK-{ticket['id']:03d}] {ticket['titre']}"
        existing = models.execute_kw(DB, uid, pwd, 'project.task', 'search',
                                     [[('name', '=', task_name)]])
        if existing:
            print(f"  -> Task '{task_name}' already exists (ID: {existing[0]})")
            continue

        assignee = assignees[i % len(assignees)] if assignees else uid

        partner_id = client_ids.get(ticket['client'])
        if not partner_id:
            print(f"  Warning: Client '{ticket['client']}' not found in client_ids for ticket {task_name}")

        description = (
            f"<p><strong>Client:</strong> {ticket['client']}</p>"
            f"<p><strong>Description:</strong> {ticket['description']}</p>"
            f"<hr/>"
            f"<p><strong>Solution:</strong> {ticket['solution']}</p>"
        )

        task_vals = {
            'name': task_name,
            'project_id': project_id,
            'user_ids': [(6, 0, [assignee])],
            'partner_id': partner_id,
            'description': description,
            'date_deadline': ticket['date'],
            'company_id': alpha_id,
            'state': '1_done' if ticket['statut'] == 'résolu' else '01_in_progress',
        }

        try:
            task_id = models.execute_kw(DB, uid, pwd, 'project.task', 'create', [task_vals])
            assignee_name = "Diana Support" if assignee == diana_uid else "Evan Engineer"
            status_label = "Resolved" if ticket['statut'] == 'résolu' else "In Progress"
            print(f"  Created Task '{task_name}' (ID: {task_id}) -> {assignee_name} [{status_label}]")
        except Exception as e:
            print(f"  Warning: Could not create task: {e}")

    return project_id


# --- Main ---

def main():
    print("Full Setup (Single Company): Company + Journal + Users + Clients + Products + Sales + Tickets")
    print("=" * 90)
    uid, pwd, models = get_connection()

    alpha_id = setup_company_and_journal(models, uid, pwd)
    user_uids = setup_users(models, uid, pwd, alpha_id)

    charlie_uid = user_uids.get("Charlie CRM", uid)
    diana_uid = user_uids.get("Diana Support", uid)
    evan_uid = user_uids.get("Evan Engineer", uid)

    print(f"\nCompany Alpha ID: {alpha_id}")
    print(f"Charlie CRM UID: {charlie_uid}, Diana Support UID: {diana_uid}, Evan Engineer UID: {evan_uid}")

    client_ids = setup_clients(models, uid, pwd, alpha_id)
    product_ids = setup_products(models, uid, pwd)
    setup_sales_orders(models, uid, pwd, alpha_id, client_ids, product_ids, charlie_uid)
    project_id = setup_tickets(models, uid, pwd, alpha_id, client_ids, diana_uid, evan_uid)

    print("\n" + "=" * 90)
    print("Setup Completed Successfully! Database contains:")
    so_count = models.execute_kw(DB, uid, pwd, 'sale.order', 'search_count',
                                 [[('client_order_ref', 'like', 'SO-MIRO')]])
    task_count = models.execute_kw(DB, uid, pwd, 'project.task', 'search_count',
                                   [[('project_id', '=', project_id)]])
    print(f"  - {len(client_ids)} Clients")
    print(f"  - {len(product_ids)} Products/Services")
    print(f"  - {so_count} Sales Orders")
    print(f"  - {task_count} Support Tickets")
    print("\nCheck live records in Odoo -> Sales -> Orders / Project -> Tasks")


if __name__ == "__main__":
    main()
