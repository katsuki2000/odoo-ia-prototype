import sys, collections
from pathlib import Path
sys.path.insert(0, '.')
from config.settings import CORE_ADDONS_PATH
from code_intelligence.extractor.python import extract_odoo_models_from_file
from code_intelligence.extractor.xml import parse_views_from_xml
from code_intelligence.graph.state_field import lifecycle_field
roots = [Path(CORE_ADDONS_PATH), Path('odoo_addons')]
models = collections.defaultdict(list); buttons = collections.defaultdict(list)
for root in roots:
    for f in root.rglob('*'):
        if '/tests/' in str(f) or f.name == '__manifest__.py': continue
        try:
            if f.suffix == '.py':
                for d in extract_odoo_models_from_file(f):
                    key = d.name or (d.inherit[0] if d.inherit else None)
                    if key: models[key].append(d)
            elif f.suffix == '.xml':
                for v in parse_views_from_xml(f):
                    if v.model: buttons[v.model].extend(v.buttons)
        except Exception: pass
print('modeles', len(models), '| modeles avec boutons', len(buttons))
has_state = lambda decls: any(fl.name == 'state' for d in decls for fl in d.fields)
same = 0; diff = []; lost = []; gained = []
for name, decls in sorted(models.items()):
    lf = lifecycle_field(decls, buttons.get(name, ()))
    hs = has_state(decls)
    if hs and lf == 'state': same += 1
    elif hs and lf: diff.append((name, lf))
    elif hs: lost.append(name)
    elif lf: gained.append((name, lf))
print(f'state et meme champ: {same} | champ different: {len(diff)} | workflow perdu: {len(lost)} | gagnes: {len(gained)}')
print('DIFF:', diff)
print('LOST:', lost)
print('GAIN:', gained)
key = ['sale.order','purchase.order','account.move','stock.picking','hr.leave','mrp.production','project.task','custom.asset.loan','custom.purchase.request']
print('CLES:', {m: lifecycle_field(models[m], buttons.get(m, ())) for m in key if m in models})
