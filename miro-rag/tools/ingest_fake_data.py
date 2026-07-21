#!/usr/bin/env python3
"""
tools/ingest_fake_data.py

Day 2 Step 1A: Ingest Fake Transactions into Live Odoo Database

Creates via XML-RPC:
1. Clients (res.partner): Société Dupont, Madagascar Tech, MIRO KE interne, etc.
2. Products: Implémentation Odoo 17, Formation Odoo 17, Support mensuel, etc.
3. Sales Orders from sales.json (assigned to Charlie CRM under appropriate company)
4. Project and Tasks from tickets.json (assigned to Diana Support / Evan Engineer)
"""

import xmlrpc.client
import json
import sys
import os

URL = "http://localhost:8069"
DB = "odoo-dev"
USERNAME = "admin"
PASSWORDS_TO_TRY = ["admin", "odoo"]

FAKE_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fake_data")


def get_connection():
    """Authenticate via XML-RPC and return uid, password, and models proxy."""
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
        print("Error: Failed to authenticate with Odoo server.")
        sys.exit(1)
    print(f"Authenticated as admin (UID: {uid})")
    models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")
    return uid, password, models


def find_or_create(models, uid, pwd, model, search_domain, create_vals, label="record"):
    """Find an existing record by domain or create a new one."""
    ids = models.execute_kw(DB, uid, pwd, model, 'search', [search_domain])
    if ids:
        print(f"  -> {label} already exists (ID: {ids[0]})")
        return ids[0]
    new_id = models.execute_kw(DB, uid, pwd, model, 'create', [create_vals])
    print(f"  Created {label} (ID: {new_id})")
    return new_id


def get_user_id_by_login(models, uid, pwd, login):
    """Retrieve user ID by login email."""
    ids = models.execute_kw(DB, uid, pwd, 'res.users', 'search', [[('login', '=', login)]])
    return ids[0] if ids else None


def get_company_id_by_name(models, uid, pwd, name):
    """Retrieve company ID by company name."""
    ids = models.execute_kw(DB, uid, pwd, 'res.company', 'search', [[('name', '=', name)]])
    return ids[0] if ids else None


def main():
    print("Day 2 Step 1A: Ingesting Fake Data into Odoo")
    print("=" * 55)
    uid, pwd, models = get_connection()

    alpha_id = get_company_id_by_name(models, uid, pwd, "Company Alpha") or 1
    beta_id = get_company_id_by_name(models, uid, pwd, "Company Beta") or 1
    charlie_uid = get_user_id_by_login(models, uid, pwd, "charlie@alpha.com") or uid
    diana_uid = get_user_id_by_login(models, uid, pwd, "diana@beta.com") or uid
    evan_uid = get_user_id_by_login(models, uid, pwd, "evan@alpha.com") or uid

    print(f"\nCompany Alpha ID: {alpha_id}, Company Beta ID: {beta_id}")
    print(f"Charlie CRM UID: {charlie_uid}, Diana Support UID: {diana_uid}, Evan Engineer UID: {evan_uid}")

    print("\n--- Part 1: Creating Clients ---")
    clients = {
        "Société Dupont": {"name": "Société Dupont", "company_type": "company",
                           "email": "contact@dupont.mg", "phone": "+261 20 22 123 45",
                           "company_id": alpha_id},
        "Madagascar Tech": {"name": "Madagascar Tech", "company_type": "company",
                            "email": "info@madatech.mg", "phone": "+261 20 22 678 90",
                            "company_id": alpha_id},
        "MIRO KE interne": {"name": "MIRO KE interne", "company_type": "company",
                            "email": "support@miroke.mg", "phone": "+261 20 22 000 00",
                            "company_id": alpha_id},
        "Telma Madagascar": {"name": "Telma Madagascar", "company_type": "company",
                             "email": "contact@telma.mg", "phone": "+261 20 23 100 00",
                             "company_id": alpha_id},
        "Groupe Socimex": {"name": "Groupe Socimex", "company_type": "company",
                           "email": "info@socimex.mg", "phone": "+261 20 22 345 67",
                           "company_id": alpha_id},
        "Brasseries Star": {"name": "Brasseries Star", "company_type": "company",
                            "email": "contact@star.mg", "phone": "+261 20 22 456 78",
                            "company_id": beta_id},
        "Air Madagascar": {"name": "Air Madagascar", "company_type": "company",
                           "email": "commercial@airmadagascar.mg", "phone": "+261 20 22 222 22",
                           "company_id": beta_id},
        "Shoprite Madagascar": {"name": "Shoprite Madagascar", "company_type": "company",
                                "email": "procurement@shoprite.mg", "phone": "+261 20 22 567 89",
                                "company_id": beta_id},
    }
    client_ids = {}
    for name, vals in clients.items():
        cid = find_or_create(models, uid, pwd, 'res.partner',
                             [('name', '=', name)], vals, label=f"Client '{name}'")
        client_ids[name] = cid

    print("\n--- Part 2: Creating Products ---")
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

    print("\n--- Part 3: Creating Sales Orders ---")
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

        partner_data = models.execute_kw(DB, uid, pwd, 'res.partner', 'read',
                                         [partner_id], {'fields': ['company_id']})
        partner_company = partner_data[0]['company_id'][0] if partner_data[0].get('company_id') else alpha_id

        so_vals = {
            'partner_id': partner_id,
            'date_order': sale['date'],
            'client_order_ref': so_name,
            'company_id': partner_company,
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
                    print(f"    Confirmed SO {so_name}")
                    # Day 2 Step 1A: Automatically create and post invoice for the confirmed Sales Order via Wizard
                    try:
                        context = {
                            'active_model': 'sale.order',
                            'active_ids': [so_id],
                            'active_id': so_id,
                        }
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
        except Exception as e:
            print(f"  Warning: Could not create SO {so_name}: {e}")

    print("\n--- Part 4: Creating Support Project & Tasks ---")
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

    assignees = [diana_uid, evan_uid]
    assignees = [a for a in assignees if a]

    for i, ticket in enumerate(tickets_data):
        task_name = f"[TK-{ticket['id']:03d}] {ticket['titre']}"
        existing = models.execute_kw(DB, uid, pwd, 'project.task', 'search',
                                     [[('name', '=', task_name)]])
        if existing:
            print(f"  -> Task '{task_name}' already exists (ID: {existing[0]})")
            continue

        assignee = assignees[i % len(assignees)] if assignees else uid

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

    print("\n" + "=" * 55)
    print("Step 1A Completed Successfully! Database contains:")

    so_count = models.execute_kw(DB, uid, pwd, 'sale.order', 'search_count',
                                 [[('client_order_ref', 'like', 'SO-MIRO')]])
    task_count = models.execute_kw(DB, uid, pwd, 'project.task', 'search_count',
                                   [[('project_id', '=', project_id)]])
    partner_count = len(client_ids)

    print(f"  - {partner_count} Clients")
    print(f"  - {len(product_ids)} Products/Services")
    print(f"  - {so_count} Sales Orders")
    print(f"  - {task_count} Support Tickets")
    print("\nCheck live records in Odoo -> Sales -> Orders / Project -> Tasks")


if __name__ == "__main__":
    main()
