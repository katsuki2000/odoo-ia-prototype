import ast
import json
import sys
from pathlib import Path

ROOT = Path('.').resolve()
SKIP = {'.venv', '.scratch', '.git', '__pycache__', 'node_modules', 'chroma_db', 'chroma_db_1024'}
PROD_ROOTS = ('core/', 'api/', 'erp_data/', 'document_rag/', 'config/', 'odoo_addons/')

CORE_EVAL = 'core/evaluation/'
ROOT_PATHS = [
    'code_intelligence',
    CORE_EVAL + 'frozen_cases.py', CORE_EVAL + 'instance_runtime.py', CORE_EVAL + 'instances',
    CORE_EVAL + 'oracles', CORE_EVAL + 'protocol', CORE_EVAL + 'protocol_metrics.py',
    CORE_EVAL + 'protocol_runner.py', CORE_EVAL + 'synthesis_bench.py', CORE_EVAL + 'system_adapter.py',
    'document_rag/verification.py',
]


def files():
    for path in ROOT.rglob('*.py'):
        rel = path.relative_to(ROOT)
        if any(part in SKIP for part in rel.parts):
            continue
        yield rel.as_posix()


def module_of(rel):
    parts = rel[:-3].split('/')
    if parts[-1] == '__init__':
        parts = parts[:-1]
    return '.'.join(parts)


all_files = sorted(files())
module_to_file = {module_of(f): f for f in all_files}
for _f in all_files:
    if _f.startswith(('scripts/', 'tests/')) and _f.count('/') == 1:
        module_to_file.setdefault(_f.rsplit('/', 1)[1][:-3], _f)


def imported_files(rel):
    try:
        tree = ast.parse((ROOT / rel).read_text(encoding='utf-8'))
    except (SyntaxError, UnicodeDecodeError):
        return set()
    package = module_of(rel).rsplit('.', 1)[0] if not rel.endswith('__init__.py') else module_of(rel)
    found = set()
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ''
            if node.level:
                anchor = package.split('.')
                anchor = anchor[:len(anchor) - (node.level - 1)] if node.level > 1 else anchor
                base = '.'.join(anchor + ([base] if base else []))
            names = [base] + [f'{base}.{alias.name}' for alias in node.names]
        for name in names:
            parts = name.split('.')
            for i in range(len(parts), 0, -1):
                target = module_to_file.get('.'.join(parts[:i]))
                if target:
                    found.add(target)
    return found


def is_root(rel):
    return any(rel == p or rel.startswith(p.rstrip('/') + '/') or rel == p + '.py' for p in ROOT_PATHS)


removed = {f for f in all_files if is_root(f)}
imports = {f: imported_files(f) for f in all_files}
unique_basename = {}
for _f in all_files:
    unique_basename.setdefault(_f.rsplit('/', 1)[-1], []).append(_f)


def defined_names(rel):
    tree = ast.parse((ROOT / rel).read_text(encoding='utf-8'))
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Name):
                        names.add(sub.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add((alias.asname or alias.name).split('.')[0])
    return names


def path_edges_and_missing(rel):
    """Fichiers cités par chemin dans des chaînes, et noms importés qui n'existent plus."""
    try:
        tree = ast.parse((ROOT / rel).read_text(encoding='utf-8'))
    except (SyntaxError, UnicodeDecodeError):
        return set(), set()
    edges, missing = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value.strip()
            if value in module_to_file_paths:
                edges.add(value)
            if value.endswith('.py') and '/' not in value and len(unique_basename.get(value, [])) == 1:
                edges.add(unique_basename[value][0])
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            target = module_to_file.get(node.module)
            if target:
                known = defined_names(target)
                for alias in node.names:
                    if alias.name != '*' and alias.name not in known and f'{node.module}.{alias.name}' not in module_to_file:
                        missing.add(alias.name)
    return edges, missing


module_to_file_paths = set(all_files)
extra = {f: path_edges_and_missing(f) for f in all_files}
for f, (edges, missing) in extra.items():
    imports[f] |= edges
ci_missing = {f for f, (_, missing) in extra.items() if any('code_intelligence' in m for m in missing)}


def is_prod(rel):
    return rel.startswith(PROD_ROOTS) and '/tests/' not in rel and not rel.startswith('tests/')


changed = True
while changed:
    changed = False
    for f in all_files:
        if f in removed or is_prod(f):
            continue
        if imports[f] & removed or f in ci_missing:
            removed.add(f)
            changed = True

prod_violations = sorted(f for f in all_files if f not in removed and is_prod(f) and (imports[f] & removed or f in ci_missing))
tests = sorted(f for f in removed if (f.startswith('tests/') or '/tests/' in f) and not f.startswith('code_intelligence/'))
scripts = sorted(f for f in removed if f.startswith('scripts/'))
other = sorted(f for f in removed if f not in tests and f not in scripts and not f.startswith('code_intelligence/')
               and not is_root(f))
ci_files = sorted(f for f in removed if f.startswith('code_intelligence/'))
prod_modules = sorted(f for f in removed if is_root(f) and not f.startswith('code_intelligence/'))
text_mentions = sorted(
    f for f in all_files
    if f not in removed and 'code_intelligence' in (ROOT / f).read_text(encoding='utf-8', errors='ignore')
)
json.dump({
    'ci_py_files': len(ci_files), 'prod_module_files': prod_modules, 'tests': tests, 'scripts': scripts,
    'other': other, 'prod_violations': prod_violations, 'text_mentions': text_mentions,
}, open('.scratch/retrait_ci/analyse.json', 'w'), indent=1)
print('code_intelligence py:', len(ci_files), '| prod modules (fichiers):', len(prod_modules),
      '| tests:', len(tests), '| scripts:', len(scripts), '| autres:', len(other))
print('violations de production:', prod_violations)
print('textes citant code_intelligence (conservés):', len(text_mentions))
