import xmlrpc.client
URL = "http://localhost:8069"
DB = "odoo-dev"
USERNAME = "admin"
common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
uid = common.authenticate(DB, USERNAME, "admin", {})
models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")
manager_id = models.execute_kw(DB, uid, "admin", 'res.users', 'search', [[('login', '=', 'manager@miro.com')]])[0]
models.execute_kw(DB, uid, "admin", 'res.users', 'write', [[manager_id], {'company_id': 1, 'company_ids': [(4, 1)]}])
m_uid = common.authenticate(DB, "manager@miro.com", "password123", {})
sales = models.execute_kw(DB, m_uid, "password123", 'sale.order', 'search', [[]])
print(f"Manager now sees {len(sales)} sales orders.")
