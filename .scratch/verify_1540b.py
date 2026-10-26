import sys
sys.path.insert(0, '.')
from erp_data.odoo_connector import OdooConnector
from config.odoo_credentials import service_login
c = OdooConnector(technical=True); uid = c.authenticate(service_login())
sr = lambda m, d, f, **k: c.search_read(uid, m, d, f, **k)
rows = sr('ir.model.access', [('model_id.model','=','stock.move.line')], ['group_id','perm_read','perm_write','perm_create','perm_unlink'])
print('ACL stock.move.line', [(r['group_id'][1] if r['group_id'] else 'GLOBAL', ''.join(k for k,p in zip('rwcu',(r['perm_read'],r['perm_write'],r['perm_create'],r['perm_unlink'])) if p)) for r in rows])
print('RULES stock.move.line', [(r['name'], r['domain_force'], r['groups'], r['global']) for r in sr('ir.rule', [('model_id.model','=','stock.move.line')], ['name','domain_force','groups','global'])])
print('MENU Moves History', [(m['complete_name'], m['action'], m['groups_id']) for m in sr('ir.ui.menu', [('name','ilike','Moves History')], ['complete_name','action','groups_id'])])
