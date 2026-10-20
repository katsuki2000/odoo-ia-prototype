"""Explicit technical metadata export from an already initialized Odoo environment."""

from datetime import datetime, timezone
import inspect
from pathlib import Path
import xml.etree.ElementTree as ET

SNAPSHOT_VERSION = 1


def _class_module(cls):
    owner = cls.__dict__.get('_module')
    if isinstance(owner, str):
        return owner
    parts = cls.__module__.split('.')
    return parts[2] if parts[:2] == ['odoo', 'addons'] and len(parts) > 2 else ''


def _callable_name(value):
    return value if isinstance(value, str) else getattr(value, '__name__', '')


def export_runtime_graph(env, modules, instanceKey, modulePaths, maxModels=200, maxRows=20000):
    """Read technical metadata only; require an explicit privileged shell session."""
    if not getattr(env, 'su', False):
        raise PermissionError('Runtime export requires an explicit superuser Odoo shell session.')
    modules = sorted(set(modules))
    if not modules or not instanceKey.strip():
        raise ValueError('Explicit module scope and instance key are required.')
    if maxModels < 1 or maxRows < 1:
        raise ValueError('Export limits must be positive.')
    def read(model, domain, fields):
        records = env[model].search_read(domain, fields=fields, limit=maxRows + 1)
        if len(records) > maxRows:
            raise ValueError(f'Metadata row limit exceeded for {model}. Narrow the module scope.')
        return records
    installed = read('ir.module.module', [('state', '=', 'installed')], ['name', 'installed_version'])
    installedNames = {row['name'] for row in installed}
    if not set(modules) <= installedNames:
        raise ValueError('Requested module scope contains modules not installed in this database.')
    roots = sorted({str(Path(path).resolve().parent) for name, path in modulePaths.items() if name in installedNames and path})
    nodes, edges, gaps = {}, [], {'missing_xmlids': 0, 'unavailable_sources': 0, 'invalid_views': 0}
    def node(key, kind, **data):
        nodes[key] = {'id': key, 'node_type': kind, 'provenance': 'odoo_runtime_snapshot', **data}
    def edge(source, target, kind, **data):
        if source in nodes and target in nodes:
            edges.append({'source': source, 'target': target, 'edge_type': kind, **data})
    def xmlids(model, rows):
        ids = [row['id'] for row in rows]
        values = env[model].browse(ids).get_external_id() if ids else {}
        for row in rows:
            if not values.get(row['id']):
                gaps['missing_xmlids'] += 1
        return values
    def relation_id(value):
        return value[0] if isinstance(value, (list, tuple)) and value else value
    selected = {}
    for name, cls in sorted(env.registry.models.items()):
        if getattr(cls, '_abstract', False):
            continue
        if any(_class_module(base) in modules for base in cls.__mro__):
            selected[name] = cls
    if len(selected) > maxModels:
        raise ValueError('Model limit exceeded. Narrow the module scope.')
    if not selected:
        raise ValueError('No effective models found for the selected installed modules.')
    for row in installed:
        if row['name'] in modules:
            node('module:' + row['name'], 'Module', name=row['name'], installed_version=row.get('installed_version', ''), depends=[])
    dependencies = read('ir.module.module.dependency', [('module_id.name', 'in', modules)], ['name', 'module_id'])
    moduleRows = read('ir.module.module', [('name', 'in', modules)], ['name'])
    moduleNames = {row['id']: row['name'] for row in moduleRows}
    for row in dependencies:
        owner = moduleNames.get(relation_id(row.get('module_id')))
        target = row['name']
        if owner and target in installedNames:
            if 'module:' + target not in nodes:
                node('module:' + target, 'Module', name=target, scope_reference=True, depends=[])
            nodes['module:' + owner]['depends'].append(target)
            edge('module:' + owner, 'module:' + target, 'DEPENDS_ON')
    for name, cls in selected.items():
        modelKey = 'model:' + name
        filepaths, sourceSites = set(), []
        node(modelKey, 'Model', name=name, description=str(getattr(cls, '_description', name)),
             description_source='runtime', filepaths=[], behavioral_tags=[], technical_tags=[])
        for base in cls.__mro__:
            owner = _class_module(base)
            if owner not in installedNames:
                continue
            if 'module:' + owner not in nodes:
                node('module:' + owner, 'Module', name=owner, scope_reference=True, depends=[])
            edge(modelKey, 'module:' + owner, 'DEFINED_IN', role='runtime_composition')
            try:
                classPath = Path(inspect.getsourcefile(base)).resolve()
                if not any(Path(root) in classPath.parents for root in roots):
                    raise ValueError('Source outside addon roots.')
                filepaths.add(str(classPath))
                site = {'module': owner, 'filepath': str(classPath)}
                if site not in sourceSites:
                    sourceSites.append(site)
            except (OSError, TypeError, ValueError):
                gaps['unavailable_sources'] += 1
        nodes[modelKey]['filepaths'] = sorted(filepaths)
        nodes[modelKey]['source_sites'] = sourceSites
        for fieldName, field in sorted(cls._fields.items()):
            key = f'field:{name}.{fieldName}'
            related = getattr(field, 'related', None)
            node(key, 'Field', name=fieldName, model=name, field_type=field.type,
                 label=str(getattr(field, 'string', fieldName) or fieldName), label_source='runtime',
                 comodel_name=getattr(field, 'comodel_name', None), compute=_callable_name(getattr(field, 'compute', None)),
                 related='.'.join(related) if isinstance(related, (tuple, list)) else related,
                 store=bool(getattr(field, 'store', False)), behavioral_tags=[], technical_tags=[])
            edge(modelKey, key, 'HAS_FIELD')
    for name in selected:
        for fieldName, field in selected[name]._fields.items():
            target = getattr(field, 'comodel_name', '')
            edge(f'field:{name}.{fieldName}', 'model:' + (target or ''), 'RELATES_TO')
    modelRows = read('ir.model', [('model', 'in', list(selected))], ['model'])
    modelNames = {row['id']: row['model'] for row in modelRows}
    groups = read('res.groups', [], ['name', 'implied_ids'])
    groupIds = xmlids('res.groups', groups)
    for row in groups:
        if groupIds.get(row['id']):
            node('group:' + groupIds[row['id']], 'Group', xml_id=groupIds[row['id']], name=row['name'])
    for row in groups:
        for target in row.get('implied_ids', []):
            edge('group:' + groupIds.get(row['id'], ''), 'group:' + groupIds.get(target, ''), 'IMPLIES')
    for table, kind, prefix, relation in [('ir.model.access', 'AccessEntry', 'acl:', 'GRANTED_BY'),
                                          ('ir.rule', 'Rule', 'rule:', 'RESTRICTED_BY')]:
        fields = ['name', 'model_id', 'perm_read', 'perm_write', 'perm_create', 'perm_unlink', 'active']
        fields += ['group_id'] if kind == 'AccessEntry' else ['groups', 'domain_force']
        rows = read(table, [('model_id', 'in', list(modelNames))], fields)
        identifiers = xmlids(table, rows)
        for row in rows:
            identifier = identifiers.get(row['id'])
            if not identifier:
                continue
            owner = modelNames[relation_id(row['model_id'])]
            attrs = {key: row.get(key) for key in fields if key not in {'model_id', 'group_id', 'groups'}}
            node(prefix + identifier, kind, xml_id=identifier, model=owner, **attrs)
            edge('model:' + owner, prefix + identifier, relation)
            targets = ([relation_id(row['group_id'])] if row.get('group_id') else []) if kind == 'AccessEntry' else row.get('groups', [])
            if kind == 'AccessEntry':
                nodes[prefix + identifier]['all_authenticated'] = not targets
            for target in targets:
                edge(prefix + identifier, 'group:' + groupIds.get(target, ''), 'APPLIES_TO_GROUP')
    actions = read('ir.actions.act_window', [('res_model', 'in', list(selected))], ['name', 'res_model'])
    actionIds = xmlids('ir.actions.act_window', actions)
    for row in actions:
        if actionIds.get(row['id']):
            node('action:' + actionIds[row['id']], 'Action', xml_id=actionIds[row['id']], name=row['name'], res_model=row['res_model'])
            edge('action:' + actionIds[row['id']], 'model:' + row['res_model'], 'TARGETS_MODEL')
    menus = read('ir.ui.menu', [('action', 'in', [f"ir.actions.act_window,{row['id']}" for row in actions])], ['name', 'action', 'parent_id', 'groups_id'])
    menuIds = xmlids('ir.ui.menu', menus)
    for row in menus:
        if menuIds.get(row['id']):
            node('menu:' + menuIds[row['id']], 'Menu', xml_id=menuIds[row['id']], name=row['name'],
                 groups=[groupIds[value] for value in row.get('groups_id', []) if groupIds.get(value)])
    for row in menus:
        actionId = int(row['action'].split(',')[1]) if row.get('action') else None
        action = next((item for item in actions if item['id'] == actionId), None)
        if action and menuIds.get(row['id']):
            edge('menu:' + menuIds[row['id']], 'action:' + actionIds.get(actionId, ''), 'EXECUTES_ACTION')
            edge('menu:' + menuIds[row['id']], 'model:' + action['res_model'], 'OPENS_MODEL', via='runtime_act_window')
    views = read('ir.ui.view', [('model', 'in', list(selected)), ('active', '=', True)], ['name', 'model', 'arch_db', 'inherit_id'])
    viewIds = xmlids('ir.ui.view', views)
    for row in views:
        identifier = viewIds.get(row['id'])
        if not identifier:
            continue
        node('view:' + identifier, 'View', xml_id=identifier, name=row['name'], model=row['model'], composition='declaration_not_effective_view')
        edge('model:' + row['model'], 'view:' + identifier, 'HAS_VIEW')
        try:
            if '<!DOCTYPE' in row['arch_db'].upper():
                raise ValueError('DTD unsupported.')
            tree = ET.fromstring(row['arch_db'])
            for button in tree.iter('button'):
                if not button.get('name'):
                    continue
                key = f"button:{row['model']}.{identifier}.{button.get('name')}"
                node(key, 'Button', model=row['model'], name=button.get('name'), label=button.get('string', ''),
                     button_type=button.get('type', ''), groups=button.get('groups', '').split(',') if button.get('groups') else [],
                     invisible=button.get('invisible', ''), view_xml_id=identifier, declaration_only=True)
                edge('view:' + identifier, key, 'HAS_BUTTON')
        except (ET.ParseError, TypeError, ValueError):
            gaps['invalid_views'] += 1
    metadata = {'generation_mode': 'runtime_metadata', 'snapshot_version': SNAPSHOT_VERSION,
                'instance_key': instanceKey, 'database': env.cr.dbname, 'module_scope': modules,
                'exported_at': datetime.now(timezone.utc).isoformat(), 'language': env.context.get('lang'),
                'addon_roots_ordered': roots, 'coverage_gaps': gaps,
                'limitations': ['Snapshot, not live state.', 'Views/buttons are declarations, not requester-effective visibility.',
                                'No inferred workflows or complete Python call graph.',
                                'Methods are discovered from source files on demand, not exported as a runtime override chain.', 'Security metadata does not establish an action approval verdict.'],
                'available_ci_tools': ['list_involved_modules', 'resolve_technical_name', 'read_source_code']}
    return {'directed': True, 'multigraph': False, 'graph': metadata,
            'nodes': list(nodes.values()), 'edges': edges}
