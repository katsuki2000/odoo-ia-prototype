import sys, collections
from pathlib import Path
sys.path.insert(0, '.')
from config.settings import CORE_ADDONS_PATH
from code_intelligence.extractor.python import extract_odoo_models_from_file
from code_intelligence.extractor.xml import parse_views_from_xml
from code_intelligence.graph.state_field import selection_fields, button_references, written_options
from code_intelligence.graph.workflow_extraction import selection_values
T = {'project.task', 'stock.move', 'payment.provider', 'hr.expense'}
models = collections.defaultdict(list); buttons = collections.defaultdict(list)
for f in Path(CORE_ADDONS_PATH).rglob('*'):
    if '/tests/' in str(f): continue
    try:
        if f.suffix == '.py':
            for d in extract_odoo_models_from_file(f):
                key = d.name or (d.inherit[0] if d.inherit else None)
                if key in T: models[key].append(d)
        elif f.suffix == '.xml':
            for v in parse_views_from_xml(f):
                if v.model in T: buttons[v.model].extend(v.buttons)
    except Exception: pass
for m in sorted(T):
    d = models[m]; c = button_references(d, buttons[m])
    print(m, 'boutons', len(buttons[m]))
    for n in selection_fields(d):
        print('   ', n, 'options', (selection_values(d, n) or [])[:5], 'refs', c[n], 'ecrites', written_options(d, n))
    ex = [b.invisible for b in buttons[m] if b.invisible][:3]
    print('    exemples invisible:', ex)
