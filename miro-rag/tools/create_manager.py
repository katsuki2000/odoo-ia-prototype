import xmlrpc.client
import sys

URL = "http://localhost:8069"
DB = "odoo-dev"
USERNAME = "admin"

def get_connection():
    common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
    uid = None
    password = None
    for pwd in ["admin", "odoo"]:
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
    models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")
    return uid, password, models

uid, pwd, models = get_connection()

# Find Alpha and Beta (Create them if they don't exist since it's a fresh DB)
alpha_ids = models.execute_kw(DB, uid, pwd, 'res.company', 'search', [[('name', '=', 'Company Alpha')]])
if not alpha_ids:
    alpha_id = models.execute_kw(DB, uid, pwd, 'res.company', 'create', [{'name': 'Company Alpha'}])
else:
    alpha_id = alpha_ids[0]

beta_ids = models.execute_kw(DB, uid, pwd, 'res.company', 'search', [[('name', '=', 'Company Beta')]])
if not beta_ids:
    beta_id = models.execute_kw(DB, uid, pwd, 'res.company', 'create', [{'name': 'Company Beta'}])
else:
    beta_id = beta_ids[0]

# Check if manager already exists
manager_ids = models.execute_kw(DB, uid, pwd, 'res.users', 'search', [[('login', '=', 'manager@miro.com')]])
if manager_ids:
    manager_uid = manager_ids[0]
    print(f"Manager already exists: {manager_uid}")
else:
    def get_group_id(xml_id):
        module, name = xml_id.split('.')
        rec = models.execute_kw(DB, uid, pwd, 'ir.model.data', 'search_read', 
                                [[('module', '=', module), ('name', '=', name)]], 
                                {'fields': ['res_id']})
        return rec[0]['res_id'] if rec else None

    groups = [
        get_group_id('base.group_erp_manager'),
        get_group_id('sales_team.group_sale_manager'),
        get_group_id('project.group_project_manager'),
        get_group_id('stock.group_stock_manager'),
        get_group_id('account.group_account_manager')
    ]
    groups = [g for g in groups if g] # filter out None

    # Create manager
    manager_vals = {
        'name': 'Miro Manager',
        'login': 'manager@miro.com',
        'password': 'password123',
        'company_id': 1,
        'company_ids': [(6, 0, [1, alpha_id, beta_id])],
        'groups_id': [(6, 0, groups)]
    }
    manager_uid = models.execute_kw(DB, uid, pwd, 'res.users', 'create', [manager_vals])
    print(f"Created Manager: {manager_uid}")

# Test what manager sees
common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
m_uid = common.authenticate(DB, "manager@miro.com", "password123", {})
if m_uid:
    print(f"Authenticated as Manager: {m_uid}")
    sales = models.execute_kw(DB, m_uid, "password123", 'sale.order', 'search', [[]])
    print(f"Manager sees {len(sales)} sales orders.")
else:
    print("Failed to authenticate as manager.")
