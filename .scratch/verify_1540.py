import re, sys
sys.path.insert(0, '.')
from erp_data.odoo_connector import OdooConnector
from config.odoo_credentials import service_login

c = OdooConnector(technical=True)
uid = c.authenticate(service_login())
print('db', c.db, 'uid ok')
sr = lambda m, d, f, **k: c.search_read(uid, m, d, f, **k)

mods = ['sale','sale_management','sale_stock','sale_purchase','purchase','purchase_stock','stock','account','sale_delivery_state','sale_invoice_policy','sale_invoice_frequency','sale_automatic_workflow','sale_order_priority','sale_blanket_order','sale_order_lock','ext_purchase_request','base_exception','sale_stock_delivery_state','sale_purchase_procurement_group_by_line','miro_credit_note_approval']
print('MODULES', {r['name']: r['state'] for r in sr('ir.module.module', [('name','in',mods)], ['name','state'])}, 'missing:', sorted(set(mods)-{r['name'] for r in sr('ir.module.module', [('name','in',mods)], ['name'])}))

def grp(xmlids):
    out = {}
    for x in xmlids:
        mod, name = x.split('.')
        d = sr('ir.model.data', [('module','=',mod),('name','=',name),('model','=','res.groups')], ['res_id'])
        if d:
            g = sr('res.groups', [('id','=',d[0]['res_id'])], ['full_name','implied_ids'])[0]
            out[x] = (d[0]['res_id'], g['full_name'])
        else:
            out[x] = None
    return out
G = grp(['purchase.group_purchase_user','purchase.group_purchase_manager','sales_team.group_sale_salesman','sales_team.group_sale_salesman_all_leads','sales_team.group_sale_manager','sale.group_auto_done_setting','stock.group_stock_user','stock.group_stock_manager','base.group_user','base.group_portal','account.group_account_manager','account.group_account_invoice','account.group_account_user','stock.group_stock_multi_locations'])
print('GROUPS', G)
gid = {k: v[0] for k, v in G.items() if v}

def acl(model):
    rows = sr('ir.model.access', [('model_id.model','=',model)], ['name','group_id','perm_read','perm_write','perm_create','perm_unlink'])
    return [(r['group_id'][1] if r['group_id'] else 'GLOBAL', ''.join(k for k, p in zip('rwcu', (r['perm_read'], r['perm_write'], r['perm_create'], r['perm_unlink'])) if p)) for r in rows]
for m in ['purchase.order','stock.quant','stock.move','stock.lot']:
    print('ACL', m, acl(m))
for m in ['sale.order','purchase.order','stock.quant','stock.move']:
    rows = sr('ir.rule', [('model_id.model','=',m)], ['name','domain_force','groups','global','perm_read','perm_write','perm_create','perm_unlink'])
    print('RULES', m, [(r['name'], r['domain_force'], [g for g in r['groups']], r['global']) for r in rows])
print('RULE_GROUP_NAMES', {r['id']: r['full_name'] for r in sr('res.groups', [('id','in', list({g for m in ['sale.order'] for r in sr('ir.rule',[('model_id.model','=',m)],['groups']) for g in r['groups']}))], ['full_name'])})

def buttons(model, names):
    views = sr('ir.ui.view', [('model','=',model),('type','=','form')], ['arch_db','groups_id','name'])
    for v in views:
        for n in names:
            for mt in re.finditer(r'<button[^>]*name="%s"[^>]*>' % n, v['arch_db'] or ''):
                print('BUTTON', model, v['name'], mt.group(0)[:300], 'viewgroups', v['groups_id'])
buttons('purchase.order', ['button_confirm','button_approve'])
buttons('sale.order', ['action_unlock','action_lock','action_confirm'])
for model, fields_ in [('stock.picking', ['location_id','location_dest_id'])]:
    views = sr('ir.ui.view', [('model','=',model),('type','=','form')], ['arch_db','name'])
    for v in views:
        for f in fields_:
            for mt in re.finditer(r'<field[^>]*name="%s"[^>]*>' % f, v['arch_db'] or ''):
                print('FIELD', v['name'], mt.group(0)[:250])
