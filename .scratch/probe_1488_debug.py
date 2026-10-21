import sys, collections
from pathlib import Path
sys.path.insert(0, '.')
from config.settings import CORE_ADDONS_PATH
from code_intelligence.extractor.python import extract_odoo_models_from_file
from code_intelligence.graph.state_field import selection_options, written_constants
targets = {'hr.leave', 'mrp.production', 'sale.order.line', 'stock.move.line', 'project.task', 'account.move', 'hr.expense.sheet', 'sale.order'}
models = collections.defaultdict(list)
for f in Path(CORE_ADDONS_PATH).rglob('*.py'):
    if '/tests/' in str(f): continue
    try:
        for d in extract_odoo_models_from_file(f):
            key = d.name or (d.inherit[0] if d.inherit else None)
            if key in targets: models[key].append(d)
    except Exception: pass
for name in sorted(targets):
    decls = models[name]
    sel = sorted({fl.name for d in decls for fl in d.fields if fl.field_type == 'Selection' and not fl.compute})
    print(name, 'decls', len(decls))
    for n in sel:
        if n in ('state','priority','approval_state','l10n_hu_edi_state') :
            print('   ', n, 'options', selection_options(decls, n)[:6], 'written', written_constants(decls, n)[:6])
