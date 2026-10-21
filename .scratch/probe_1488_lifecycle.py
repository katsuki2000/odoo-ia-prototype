import sys, collections
from pathlib import Path
sys.path.insert(0, '.')
from config.settings import CORE_ADDONS_PATH
from code_intelligence.extractor.python import extract_odoo_models_from_file
from code_intelligence.graph.state_field import lifecycle_field, selection_options, written_constants
roots = [Path(CORE_ADDONS_PATH), Path('odoo_addons')]
models = collections.defaultdict(list)
for root in roots:
    for f in root.rglob('*.py'):
        if '/tests/' in str(f) or f.name == '__manifest__.py':
            continue
        try:
            for d in extract_odoo_models_from_file(f):
                key = d.name or (d.inherit[0] if d.inherit else None)
                if key: models[key].append(d)
        except Exception:
            pass
print('modeles', len(models))
has_state = lambda decls: any(fl.name == 'state' and fl.field_type == 'Selection' for d in decls for fl in d.fields)
same = diff = lost = gained = 0; rows_diff = []; rows_lost = []; rows_gain = []
for name, decls in sorted(models.items()):
    lf = lifecycle_field(decls)
    hs = has_state(decls)
    if hs and lf == 'state': same += 1
    elif hs and lf: diff += 1; rows_diff.append((name, lf))
    elif hs and not lf: lost += 1; rows_lost.append(name)
    elif lf: gained += 1; rows_gain.append((name, lf))
print('state selection + lifecycle=state:', same, '| lifecycle autre champ:', diff, '| state sans ecriture detectee (perdrait son workflow):', lost, '| modeles sans state qui gagnent un champ:', gained)
print('DIFF:', rows_diff[:25])
print('LOST (extrait):', rows_lost[:40])
print('GAIN:', rows_gain[:40])
