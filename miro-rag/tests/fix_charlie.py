import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.ingest_fake_data import get_connection, get_user_id_by_login
from tools.create_day2_setup import get_group_id

uid, pwd, models = get_connection()
charlie_uid = get_user_id_by_login(models, uid, pwd, "charlie@alpha.com")

xml_ids = [
    "sales_team.group_sale_salesman_all_leads",
    "account.group_account_invoice",
    "project.group_project_user"
]

group_ids = []
for xml_id in xml_ids:
    gid = get_group_id(models, uid, pwd, xml_id)
    if gid:
        group_ids.append(gid)

models.execute_kw("odoo-dev", uid, pwd, 'res.users', 'write', [[charlie_uid], {'groups_id': [(4, gid) for gid in group_ids]}])
print("✅ Charlie CRM a maintenant les droits de lecture sur tout Alpha (Sales, Factures, Projets).")
