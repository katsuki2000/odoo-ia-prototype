#!/usr/bin/env python3
"""
Day 2 Setup Automation Script:
Connects to Odoo 17 via XML-RPC and automatically sets up:
1. Two Companies: Company Alpha & Company Beta
2. Six Specialized Users across different departments with appropriate company access and roles.
"""

import xmlrpc.client
import sys

# Odoo Connection Parameters
URL = "http://localhost:8069"
DB = "odoo-dev"
USERNAME = "admin"
PASSWORDS_TO_TRY = ["admin", "odoo"]

def get_connection():
    common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
    uid = None
    valid_password = None
    
    for pwd in PASSWORDS_TO_TRY:
        try:
            uid = common.authenticate(DB, USERNAME, pwd, {})
            if uid:
                valid_password = pwd
                break
        except Exception as e:
            continue
            
    if not uid:
        print("❌ Failed to authenticate with Odoo. Please check credentials or DB name.")
        sys.exit(1)
        
    print(f"✅ Successfully authenticated as user ID {uid} (admin)")
    models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")
    return uid, valid_password, models

def get_or_create_company(models, uid, password, name):
    company_ids = models.execute_kw(DB, uid, password, 'res.company', 'search', [[('name', '=', name)]])
    if company_ids:
        print(f"🏢 Company '{name}' already exists (ID: {company_ids[0]})")
        return company_ids[0]
    
    company_id = models.execute_kw(DB, uid, password, 'res.company', 'create', [{'name': name}])
    print(f"✨ Created Company '{name}' (ID: {company_id})")
    return company_id

def get_group_id(models, uid, password, xml_id):
    if "." not in xml_id:
        return None
    module, name = xml_id.split(".", 1)
    res = models.execute_kw(DB, uid, password, 'ir.model.data', 'search_read',
                            [[('module', '=', module), ('name', '=', name)]],
                            {'fields': ['res_id']})
    if res:
        return res[0]['res_id']
    return None

def main():
    print("🚀 Starting Day 2 Automated Setup via XML-RPC...\n" + "="*50)
    uid, password, models = get_connection()
    
    # 1. Create Companies
    print("\n--- Step 1: Setting up Companies ---")
    alpha_id = get_or_create_company(models, uid, password, "Company Alpha")
    beta_id = get_or_create_company(models, uid, password, "Company Beta")
    
    # 2. Get Internal User group ID (base.group_user is required for backend access)
    internal_user_group = get_group_id(models, uid, password, "base.group_user")
    
    # Define 6 Specialized Users
    users_data = [
        {
            "name": "Alice Admin",
            "login": "alice@alpha.com",
            "password": "password123",
            "company_id": alpha_id,
            "company_ids": [alpha_id, beta_id],
            "role": "CEO / General Manager (Multi-Company)",
            "groups": ["base.group_user", "sales_team.group_sale_manager", "project.group_project_manager"]
        },
        {
            "name": "Bob Buyer",
            "login": "bob@alpha.com",
            "password": "password123",
            "company_id": alpha_id,
            "company_ids": [alpha_id],
            "role": "Purchasing & Inventory Manager (Company Alpha)",
            "groups": ["base.group_user", "purchase.group_purchase_manager", "stock.group_stock_manager"]
        },
        {
            "name": "Charlie CRM",
            "login": "charlie@alpha.com",
            "password": "password123",
            "company_id": alpha_id,
            "company_ids": [alpha_id],
            "role": "Sales & CRM Specialist (Company Alpha)",
            "groups": ["base.group_user", "sales_team.group_sale_salesman"]
        },
        {
            "name": "Diana Support",
            "login": "diana@beta.com",
            "password": "password123",
            "company_id": beta_id,
            "company_ids": [beta_id],
            "role": "Helpdesk & Service Specialist (Company Beta)",
            "groups": ["base.group_user", "project.group_project_user"]
        },
        {
            "name": "Evan Engineer",
            "login": "evan@alpha.com",
            "password": "password123",
            "company_id": alpha_id,
            "company_ids": [alpha_id, beta_id],
            "role": "Project & Manufacturing Engineer (Multi-Company)",
            "groups": ["base.group_user", "project.group_project_user", "stock.group_stock_user"]
        },
        {
            "name": "Fiona Finance",
            "login": "fiona@beta.com",
            "password": "password123",
            "company_id": beta_id,
            "company_ids": [beta_id],
            "role": "Billing & Accounting Specialist (Company Beta)",
            "groups": ["base.group_user", "account.group_account_invoice"]
        }
    ]
    
    print("\n--- Step 2: Setting up 6 Specialized Users ---")
    created_users = []
    
    for u in users_data:
        user_ids = models.execute_kw(DB, uid, password, 'res.users', 'search', [[('login', '=', u['login'])]])
        if user_ids:
            print(f"👤 User '{u['name']}' ({u['login']}) already exists (ID: {user_ids[0]})")
            created_users.append((u['name'], u['login'], u['role'], "Existing"))
            continue
            
        # Build groups list
        group_ids = []
        for xml_id in u['groups']:
            gid = get_group_id(models, uid, password, xml_id)
            if gid and gid not in group_ids:
                group_ids.append(gid)
        if internal_user_group and internal_user_group not in group_ids:
            group_ids.append(internal_user_group)
            
        user_vals = {
            'name': u['name'],
            'login': u['login'],
            'password': u['password'],
            'company_id': u['company_id'],
            'company_ids': [(6, 0, u['company_ids'])],
        }
        if group_ids:
            user_vals['groups_id'] = [(6, 0, group_ids)]
            
        try:
            new_id = models.execute_kw(DB, uid, password, 'res.users', 'create', [user_vals])
            print(f"✨ Created User '{u['name']}' ({u['login']}) - Role: {u['role']} (ID: {new_id})")
            created_users.append((u['name'], u['login'], u['role'], "Created"))
        except Exception as e:
            print(f"⚠️ Could not create user '{u['name']}': {e}")
            
    print("\n" + "="*50)
    print("🎉 Day 2 Setup Complete! Here is your team summary:\n")
    print(f"{'Name':<15} | {'Login / Email':<18} | {'Status':<10} | {'Role & Company':<40}")
    print("-" * 88)
    for name, login, role, status in created_users:
        print(f"{name:<15} | {login:<18} | {status:<10} | {role:<40}")
    print("-" * 88)
    print("\n💡 All users have default password: password123")
    print("🌐 You can now log into Odoo or check Settings -> Users & Companies -> Users!")

if __name__ == "__main__":
    main()
