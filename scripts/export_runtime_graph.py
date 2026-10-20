"""Run from the repository root through an explicit Odoo 17 shell session."""

import json
import os
from pathlib import Path
import runpy
import tempfile

from odoo.modules.module import get_module_path

if 'env' not in globals():
    raise RuntimeError('Run this script through Odoo shell, not a plain Python interpreter.')

moduleScope = [name.strip() for name in os.getenv('CI_RUNTIME_GRAPH_MODULES', '').split(',') if name.strip()]
instanceKey = os.getenv('CI_RUNTIME_GRAPH_INSTANCE', '').strip()
outputPath = os.getenv('CI_RUNTIME_GRAPH_PATH', '').strip()
if not moduleScope or not instanceKey or not outputPath:
    raise ValueError('Set CI_RUNTIME_GRAPH_MODULES, CI_RUNTIME_GRAPH_INSTANCE and CI_RUNTIME_GRAPH_PATH explicitly.')

exporter = runpy.run_path(str(Path.cwd() / 'code_intelligence/graph/runtime_export.py'))['export_runtime_graph']
installed = env['ir.module.module'].search_read([('state', '=', 'installed')], fields=['name'], limit=20001)
if len(installed) > 20000:
    raise ValueError('Installed-module export limit exceeded.')
modulePaths = {row['name']: get_module_path(row['name']) for row in installed}
try:
    snapshot = exporter(env, moduleScope, instanceKey, modulePaths,
                        maxModels=int(os.getenv('CI_RUNTIME_GRAPH_MAX_MODELS', '200')),
                        maxRows=int(os.getenv('CI_RUNTIME_GRAPH_MAX_ROWS', '20000')))
    destination = Path(outputPath).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporaryPath = tempfile.mkstemp(prefix='.runtime-graph-', dir=destination.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump(snapshot, handle, ensure_ascii=False)
        os.replace(temporaryPath, destination)
    finally:
        if os.path.exists(temporaryPath):
            os.unlink(temporaryPath)
    print(f"Runtime graph exported: {len(snapshot['nodes'])} nodes, {len(snapshot['edges'])} edges. Review snapshot coverage before use.")
finally:
    env.cr.rollback()
