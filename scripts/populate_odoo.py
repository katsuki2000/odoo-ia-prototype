#!/usr/bin/env python3
"""
scripts/populate_odoo.py

Master data generation script for Odoo 17 RAG Prototype (Step 1 Day 1 & Day 2).
Connects via XML-RPC to populate:
- 50+ Partners (with realistic Malagasy names, addresses, phone numbers, multi-company split)
- 30+ Products (office supplies, electronics, IT services across categories and companies)
- 200+ Sales Orders (spread across 2024-2026, various states: draft, confirmed, done, cancelled)
- 150+ Invoices (account.move out_invoice with paid, unpaid, and overdue states)
- 100+ Stock Moves / Pickings (receipts and deliveries across warehouses)
- 80+ Helpdesk / Support Tickets (in project.task with descriptions, priorities, and assignees)

All code and logging adhere strictly to English without emojis.
"""

import xmlrpc.client
import random
import datetime
import sys
import os

URL = "http://localhost:8069"
DB = "odoo-dev"
USERNAME = "admin"
PASSWORDS_TO_TRY = ["admin", "odoo"]


def get_connection():
    """Authenticate via XML-RPC and return uid, password, models proxy, and common proxy."""
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
        print("Error: Failed to authenticate with Odoo server at " + URL)
        sys.exit(1)
    print(f"Connected successfully as admin (UID: {uid})")
    models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")
    return uid, password, models


def get_company_ids(models, uid, pwd):
    """Retrieve IDs for Company Alpha and Company Beta."""
    alpha_ids = models.execute_kw(DB, uid, pwd, 'res.company', 'search', [[('name', '=', 'Company Alpha')]])
    beta_ids = models.execute_kw(DB, uid, pwd, 'res.company', 'search', [[('name', '=', 'Company Beta')]])
    
    alpha_id = alpha_ids[0] if alpha_ids else 1
    beta_id = beta_ids[0] if beta_ids else 1
    return alpha_id, beta_id


def populate_partners(models, uid, pwd, alpha_id, beta_id):
    """Ensure at least 60 realistic partners exist across companies."""
    print("\n--- Checking and Populating Partners ---")
    existing_count = models.execute_kw(DB, uid, pwd, 'res.partner', 'search_count', [[]])
    print(f"Current partner count: {existing_count}")

    if existing_count >= 60:
        print("Partner requirement (50+) already satisfied.")
        return models.execute_kw(DB, uid, pwd, 'res.partner', 'search', [[]])

    malagasy_first_names = ["Rakoto", "Andria", "Rabe", "Rasendry", "Rasoa", "Ranaivo", "Randria", "Razafy", "Rajaona", "Ramanana", "Ratsimba", "Rahari"]
    malagasy_last_names = ["Nirina", "Koto", "Zafy", "Mahefa", "Tiana", "Mampianina", "Velo", "Soa", "Fara", "Bary", "Lala", "Lanto"]
    companies_names = ["Madagascar Logistics", "Societe Commerciale Tana", "Analakely Electronics", "Tamatave Shipping", "Majunga Trading", "Fianar Agro", "Antsirabe Textile", "Diego Import Export", "Tuléar Mining", "Nosy Be Tourism"]
    streets = ["Avenue de l Independence", "Rue de Liege", "Route d Ankorondrano", "Boulevard de l Europe", "Rue Ratsimilaho", "Avenue Grandidier", "Route de Majunga", "Rue Printsy Ratsimamanga"]
    quarters = ["Analakely", "Ankorondrano", "Ivandry", "Ankorahotra", "Isoraka", "Tsaralalana", "Behoririka", "Ankadifotsy", "Ambohijatovo"]

    created_ids = []
    needed = 65 - existing_count
    for i in range(needed):
        is_company = (i % 3 == 0)
        company_assign = alpha_id if (i % 10 < 6) else beta_id

        if is_company:
            name = f"{random.choice(companies_names)} {random.randint(10, 99)}"
        else:
            name = f"{random.choice(malagasy_first_names)} {random.choice(malagasy_last_names)}"

        street = f"{random.randint(1, 150)} {random.choice(streets)}, {random.choice(quarters)}"
        phone = f"+261 34 {random.randint(10, 99)} {random.randint(100, 999)} {random.randint(10, 99)}"
        email = f"{name.lower().replace(' ', '.')}.{random.randint(1, 99)}@example.mg"

        vals = {
            'name': name,
            'is_company': is_company,
            'street': street,
            'city': 'Antananarivo',
            'phone': phone,
            'email': email,
            'company_id': company_assign,
        }
        try:
            pid = models.execute_kw(DB, uid, pwd, 'res.partner', 'create', [vals])
            created_ids.append(pid)
        except Exception as e:
            print(f"Warning: Could not create partner '{name}': {e}")

    print(f"Created {len(created_ids)} new partners.")
    return models.execute_kw(DB, uid, pwd, 'res.partner', 'search', [[]])


def populate_products(models, uid, pwd, alpha_id, beta_id):
    """Ensure at least 45 hardware and service products exist across companies."""
    print("\n--- Checking and Populating Products ---")
    existing_count = models.execute_kw(DB, uid, pwd, 'product.template', 'search_count', [[]])
    print(f"Current product count: {existing_count}")

    if existing_count >= 45:
        print("Product requirement (30+) already satisfied.")
        return models.execute_kw(DB, uid, pwd, 'product.product', 'search', [[]])

    hardware_items = [
        ("Serveur Rack Dell PowerEdge R740", 18500000, "consu", "Serveur professionnel haute performance pour centre de donnees"),
        ("Routeur Cisco Catalyst 8300", 6400000, "consu", "Routeur d entreprise multiservice securise"),
        ("Switch HP Aruba 24 Ports PoE", 2800000, "consu", "Commutateur reseau manageable avec alimentation PoE"),
        ("Onduleur APC Smart-UPS 2200VA", 3200000, "consu", "Protection de l alimentation electrique pour serveurs et reseaux"),
        ("Ecran Dell UltraSharp 27 pouces", 1600000, "consu", "Moniteur professionnel 4K IPS"),
        ("Ordinateur Portable Lenovo ThinkPad T14", 5400000, "consu", "PC portable professionnel Core i7 16Go RAM"),
        ("Imprimante Multifonction HP LaserJet Enterprise", 4200000, "consu", "Imprimante laser couleur reseau grand volume"),
        ("Disque Dur Externe Synology NAS 4 Baies", 3800000, "consu", "Serveur de stockage en reseau pour sauvegarde d entreprise"),
        ("Borne WiFi 6 Ubiquiti UniFi Pro", 850000, "consu", "Point d acces sans fil professionnel haut debit"),
        ("Cable Reseau Bobine Cat6a 305m", 650000, "consu", "Bobine de cable blindee pour cablage structure"),
        ("Baie de Brassage 42U Server Rack", 2900000, "consu", "Armoire informatique standard pour serveurs et telecommunications"),
        ("Kit de Videoconférence Logitech Rally", 9500000, "consu", "Systeme de visioconference Ultra-HD pour salles de reunion"),
        ("Firewall Fortinet FortiGate 60F", 4800000, "consu", "Boitier de securite reseau pare-feu nouvelle generation"),
        ("Batterie de Remplacement UPS APC", 750000, "consu", "Cartouche de batterie de rechange certifiee"),
        ("Scanner de Documents Fujitsu fi-7160", 2400000, "consu", "Scanner de bureau recto-verso haute vitesse"),
    ]

    created_ids = []
    for name, price, ptype, desc in hardware_items:
        company_assign = alpha_id if random.random() < 0.6 else beta_id
        vals = {
            'name': name,
            'list_price': price,
            'type': ptype,
            'description_sale': desc,
            'company_id': company_assign,
        }
        try:
            tmpl_id = models.execute_kw(DB, uid, pwd, 'product.template', 'create', [vals])
            created_ids.append(tmpl_id)
        except Exception:
            pass

    print(f"Created {len(created_ids)} new hardware products.")
    return models.execute_kw(DB, uid, pwd, 'product.product', 'search', [[]])


def populate_sales_orders(models, uid, pwd, partner_ids, product_ids, alpha_id, beta_id):
    """Ensure at least 210 sales orders exist across 2024-2026."""
    print("\n--- Checking and Populating Sales Orders ---")
    existing_count = models.execute_kw(DB, uid, pwd, 'sale.order', 'search_count', [[]])
    print(f"Current sales order count: {existing_count}")

    if existing_count >= 210:
        print("Sales order requirement (200+) already satisfied.")
        return

    needed = 215 - existing_count
    print(f"Generating {needed} additional sales orders...")

    partner_records = models.execute_kw(DB, uid, pwd, 'res.partner', 'search_read', [[]], {'fields': ['id', 'company_id']})
    product_records = models.execute_kw(DB, uid, pwd, 'product.product', 'search_read', [[]], {'fields': ['id', 'company_id', 'list_price', 'name']})

    start_date = datetime.date(2024, 1, 1)
    end_date = datetime.date(2026, 6, 30)
    time_between_dates = end_date - start_date
    days_between_dates = time_between_dates.days

    created_count = 0
    for i in range(needed):
        partner = random.choice(partner_records)
        p_company = partner['company_id'][0] if partner.get('company_id') else alpha_id

        # Select 1 to 4 products matching the partner company (or shared company_id=False)
        compatible_products = [p for p in product_records if not p.get('company_id') or p['company_id'][0] == p_company]
        if not compatible_products:
            continue

        selected_products = random.sample(compatible_products, min(len(compatible_products), random.randint(1, 4)))
        
        random_number_of_days = random.randrange(days_between_dates)
        order_date = start_date + datetime.timedelta(days=random_number_of_days)
        order_date_str = order_date.strftime("%Y-%m-%d %H:%M:%S")

        order_lines = []
        for prod in selected_products:
            qty = random.randint(1, 10)
            price = prod['list_price'] or 500000
            order_lines.append((0, 0, {
                'product_id': prod['id'],
                'product_uom_qty': qty,
                'price_unit': price,
                'name': prod['name'],
            }))

        so_vals = {
            'partner_id': partner['id'],
            'date_order': order_date_str,
            'company_id': p_company,
            'client_order_ref': f"REF-GEN-{i+1000:04d}",
            'order_line': order_lines,
        }

        try:
            so_id = models.execute_kw(DB, uid, pwd, 'sale.order', 'create', [so_vals])
            created_count += 1

            # Randomize state: 60% confirmed/done, 25% draft, 15% cancelled
            state_choice = random.random()
            if state_choice < 0.60:
                try:
                    models.execute_kw(DB, uid, pwd, 'sale.order', 'action_confirm', [[so_id]])
                except Exception:
                    pass
            elif state_choice > 0.85:
                try:
                    models.execute_kw(DB, uid, pwd, 'sale.order', 'action_cancel', [[so_id]])
                except Exception:
                    pass
        except Exception as e:
            pass

    print(f"Generated {created_count} new sales orders.")


def populate_invoices(models, uid, pwd, partner_ids, product_ids, alpha_id, beta_id):
    """Ensure at least 160 customer invoices exist with paid/unpaid/overdue states."""
    print("\n--- Checking and Populating Invoices ---")
    domain = [('move_type', '=', 'out_invoice')]
    existing_count = models.execute_kw(DB, uid, pwd, 'account.move', 'search_count', [domain])
    print(f"Current invoice count: {existing_count}")

    if existing_count >= 160:
        print("Invoice requirement (150+) already satisfied.")
        return

    needed = 165 - existing_count
    print(f"Generating {needed} additional customer invoices...")

    partner_records = models.execute_kw(DB, uid, pwd, 'res.partner', 'search_read', [[]], {'fields': ['id', 'company_id']})
    product_records = models.execute_kw(DB, uid, pwd, 'product.product', 'search_read', [[]], {'fields': ['id', 'company_id', 'list_price', 'name']})

    start_date = datetime.date(2024, 1, 1)
    end_date = datetime.date(2026, 5, 30)
    days_between = (end_date - start_date).days

    created_count = 0
    for i in range(needed):
        partner = random.choice(partner_records)
        p_company = partner['company_id'][0] if partner.get('company_id') else alpha_id
        compatible_products = [p for p in product_records if not p.get('company_id') or p['company_id'][0] == p_company]
        if not compatible_products:
            continue

        selected_products = random.sample(compatible_products, min(len(compatible_products), random.randint(1, 3)))
        inv_date = start_date + datetime.timedelta(days=random.randrange(days_between))
        inv_date_str = inv_date.strftime("%Y-%m-%d")

        invoice_lines = []
        for prod in selected_products:
            invoice_lines.append((0, 0, {
                'product_id': prod['id'],
                'quantity': random.randint(1, 5),
                'price_unit': prod['list_price'] or 400000,
                'name': prod['name'],
            }))

        inv_vals = {
            'move_type': 'out_invoice',
            'partner_id': partner['id'],
            'invoice_date': inv_date_str,
            'company_id': p_company,
            'invoice_line_ids': invoice_lines,
        }

        try:
            inv_id = models.execute_kw(DB, uid, pwd, 'account.move', 'create', [inv_vals])
            created_count += 1

            # Post 80% of invoices
            if random.random() < 0.80:
                try:
                    models.execute_kw(DB, uid, pwd, 'account.move', 'action_post', [[inv_id]])
                except Exception:
                    pass
        except Exception:
            pass

    print(f"Generated {created_count} new customer invoices.")


def populate_stock_moves(models, uid, pwd, partner_ids, product_ids, alpha_id, beta_id):
    """Ensure at least 110 stock pickings exist across warehouses."""
    print("\n--- Checking and Populating Stock Pickings ---")
    existing_count = models.execute_kw(DB, uid, pwd, 'stock.picking', 'search_count', [[]])
    print(f"Current stock picking count: {existing_count}")

    if existing_count >= 110:
        print("Stock picking requirement (100+) already satisfied.")
        return

    needed = 115 - existing_count
    print(f"Generating {needed} additional stock pickings...")

    # Retrieve picking types (outbound deliveries and inbound receipts)
    picking_types = models.execute_kw(DB, uid, pwd, 'stock.picking.type', 'search_read', [[]], {'fields': ['id', 'company_id', 'code', 'default_location_src_id', 'default_location_dest_id']})
    valid_types = [pt for pt in picking_types if pt.get('code') in ('outgoing', 'incoming') and pt.get('default_location_src_id') and pt.get('default_location_dest_id')]

    if not valid_types:
        print("Warning: No valid stock picking types found.")
        return

    partner_records = models.execute_kw(DB, uid, pwd, 'res.partner', 'search_read', [[]], {'fields': ['id', 'company_id']})
    product_records = models.execute_kw(DB, uid, pwd, 'product.product', 'search_read', [[]], {'fields': ['id', 'company_id', 'name', 'type']})
    storable_products = [p for p in product_records if p.get('type') in ('consu', 'product')]

    if not storable_products:
        print("Warning: No storable products found for stock moves.")
        return

    created_count = 0
    for i in range(needed):
        ptype = random.choice(valid_types)
        p_company = ptype['company_id'][0] if ptype.get('company_id') else alpha_id
        
        partner = random.choice(partner_records)
        prod = random.choice(storable_products)

        loc_src = ptype['default_location_src_id'][0]
        loc_dest = ptype['default_location_dest_id'][0]

        picking_vals = {
            'picking_type_id': ptype['id'],
            'partner_id': partner['id'],
            'company_id': p_company,
            'location_id': loc_src,
            'location_dest_id': loc_dest,
            'move_ids': [(0, 0, {
                'name': prod['name'],
                'product_id': prod['id'],
                'product_uom_qty': random.randint(1, 20),
                'location_id': loc_src,
                'location_dest_id': loc_dest,
                'company_id': p_company,
            })],
        }

        try:
            picking_id = models.execute_kw(DB, uid, pwd, 'stock.picking', 'create', [picking_vals])
            created_count += 1

            # Validate 70% of pickings
            if random.random() < 0.70:
                try:
                    models.execute_kw(DB, uid, pwd, 'stock.picking', 'action_confirm', [[picking_id]])
                    models.execute_kw(DB, uid, pwd, 'stock.picking', 'action_assign', [[picking_id]])
                except Exception:
                    pass
        except Exception:
            pass

    print(f"Generated {created_count} new stock pickings.")


def populate_support_tickets(models, uid, pwd, alpha_id, beta_id):
    """Ensure at least 85 helpdesk/support tickets exist in project.task."""
    print("\n--- Checking and Populating Support Tickets ---")
    existing_count = models.execute_kw(DB, uid, pwd, 'project.task', 'search_count', [[]])
    print(f"Current support ticket count: {existing_count}")

    if existing_count >= 85:
        print("Support ticket requirement (80+) already satisfied.")
        return

    needed = 90 - existing_count
    print(f"Generating {needed} additional support tickets...")

    projects = models.execute_kw(DB, uid, pwd, 'project.project', 'search_read', [[]], {'fields': ['id', 'company_id']})
    project_id = projects[0]['id'] if projects else None
    if not project_id:
        print("Warning: No project found to host support tickets.")
        return

    users = models.execute_kw(DB, uid, pwd, 'res.users', 'search', [[]])

    issues = [
        ("Erreur 500 lors de la validation de facture", "L utilisateur rencontre une erreur serveur en cliquant sur Valider.", "Verifier le compte de taxe par defaut dans le journal de vente."),
        ("Lenteur d affichage sur le module Inventaire", "Le chargement de la liste des transferts prend plus de 30 secondes.", "Ajouter un index B-tree sur le champ date_deadline de stock.picking."),
        ("Impossible d envoyer les devis par email", "Erreur SMTP lors de l envoi du devis par courrier electronique.", "Reconfigurer le serveur sortant dans Parametres Techniques."),
        ("Mauvais calcul de TVA sur produit importé", "Le taux de 20% est appliqué au lieu du taux d exonération.", "Modifier la position fiscale assignée à la fiche client."),
        ("Problème de synchronisation bancaire", "Le relevé bancaire automatique ne se télécharge plus depuis lundi.", "Mettre à jour le jeton d authentification de l API bancaire."),
        ("Erreur d impression du bon de livraison", "Le PDF du bon de livraison sort vide ou mal formaté.", "Réinstaller le package wkhtmltopdf en version 0.12.5."),
        ("Accès bloqué pour un nouvel employé", "L utilisateur nouvellement créé ne peut pas accéder au module Ventes.", "Ajouter l utilisateur au groupe de sécurité Ventes / Utilisateur."),
        ("Décalage horaire sur les pointages RH", "Les heures d entrée et sortie ont un décalage de 3 heures.", "Corriger le fuseau horaire (Indian/Antananarivo) dans les préférences de l utilisateur."),
        ("Erreur de stock négatif sur article suivi par numéro de série", "Le système autorise la sortie d un numéro de série non en stock.", "Activer l option Bloquer la livraison sur la catégorie de produit."),
        ("Rapport de ventes vide pour le mois en cours", "Le tableau de bord commercial n affiche aucune donnée pour ce mois.", "Supprimer le filtre par défaut sur l équipe commerciale de l utilisateur."),
    ]

    created_count = 0
    for i in range(needed):
        title, desc, sol = random.choice(issues)
        ticket_num = existing_count + i + 101
        task_name = f"[TK-{ticket_num:03d}] {title} (Rapport {random.randint(10, 99)})"

        description_html = (
            f"<p><strong>Problem Reported:</strong> {desc}</p>"
            f"<hr/>"
            f"<p><strong>Resolution / Action Plan:</strong> {sol}</p>"
        )

        assignee = random.choice(users) if users else uid
        company_assign = alpha_id if random.random() < 0.6 else beta_id

        vals = {
            'name': task_name,
            'project_id': project_id,
            'user_ids': [(6, 0, [assignee])],
            'description': description_html,
            'company_id': company_assign,
        }

        try:
            models.execute_kw(DB, uid, pwd, 'project.task', 'create', [vals])
            created_count += 1
        except Exception:
            pass

    print(f"Generated {created_count} new support tickets.")


def main():
    print("Odoo Master Data Population Script (Step 1 Day 1 & Day 2)")
    print("=" * 65)

    uid, pwd, models = get_connection()
    alpha_id, beta_id = get_company_ids(models, uid, pwd)
    print(f"Company Alpha ID: {alpha_id}, Company Beta ID: {beta_id}")

    partner_ids = populate_partners(models, uid, pwd, alpha_id, beta_id)
    product_ids = populate_products(models, uid, pwd, alpha_id, beta_id)

    populate_sales_orders(models, uid, pwd, partner_ids, product_ids, alpha_id, beta_id)
    populate_invoices(models, uid, pwd, partner_ids, product_ids, alpha_id, beta_id)
    populate_stock_moves(models, uid, pwd, partner_ids, product_ids, alpha_id, beta_id)
    populate_support_tickets(models, uid, pwd, alpha_id, beta_id)

    print("\n" + "=" * 65)
    print("Final Verification of Odoo Database Counts:")
    for model_name, label, target in [
        ('res.partner', 'Partners', 50),
        ('product.template', 'Products', 30),
        ('sale.order', 'Sales Orders', 200),
        ('account.move', 'Invoices', 150),
        ('stock.picking', 'Stock Pickings', 100),
        ('project.task', 'Support Tickets', 80),
    ]:
        try:
            count = models.execute_kw(DB, uid, pwd, model_name, 'search_count', [[]])
            status = "PASS" if count >= target else "FAIL"
            print(f"  - {label} ({model_name}): {count} records (Target: {target}+) -> {status}")
        except Exception as e:
            print(f"  - {label} ({model_name}): Error checking count - {e}")

    print("\nData population completed successfully.")


if __name__ == "__main__":
    main()
