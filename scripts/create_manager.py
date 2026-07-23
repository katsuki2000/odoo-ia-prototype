import xmlrpc.client
import sys

URL = "http://localhost:8069"
DB = "odoo-dev"
USERNAME = "admin"

def main():
    common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
    uid = None
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
    
    # Check if manager already exists
    manager_ids = models.execute_kw(DB, uid, password, 'res.users', 'search', [[('login', '=', 'manager@miro.com')]])
    if manager_ids:
        print(f"Manager already exists: {manager_ids[0]}")
        return

    def get_group_id(xml_id):
        module, name = xml_id.split('.')
        rec = models.execute_kw(DB, uid, password, 'ir.model.data', 'search_read', 
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
    groups = [g for g in groups if g]

    manager_vals = {
        'name': 'Miro Manager',
        'login': 'manager@miro.com',
        'password': 'password123',
        'groups_id': [(6, 0, groups)]
    }
    
    manager_uid = models.execute_kw(DB, uid, password, 'res.users', 'create', [manager_vals])
    print(f"Created Manager: {manager_uid}")

if __name__ == "__main__":
    main()
