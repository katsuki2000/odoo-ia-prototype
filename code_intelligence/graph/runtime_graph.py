"""Load an explicitly generated runtime snapshot without source reconstruction."""

import hashlib
import json
from pathlib import Path

from .runtime_export import SNAPSHOT_VERSION

RUNTIME_CI_TOOLS = frozenset({'list_involved_modules', 'resolve_technical_name', 'read_source_code'})


def read_runtime_snapshot(path, expectedInstance):
    if not expectedInstance or not expectedInstance.strip():
        raise ValueError('CI_RUNTIME_GRAPH_INSTANCE is required when using a runtime snapshot.')
    content = Path(path).read_bytes()
    snapshot = json.loads(content)
    metadata = snapshot.get('graph', {})
    if metadata.get('snapshot_version') != SNAPSHOT_VERSION or metadata.get('generation_mode') != 'runtime_metadata':
        raise ValueError('Unsupported runtime graph snapshot schema.')
    if metadata.get('instance_key') != expectedInstance:
        raise ValueError('Runtime graph belongs to a different configured instance.')
    if not metadata.get('module_scope') or not metadata.get('exported_at'):
        raise ValueError('Runtime snapshot lacks explicit scope or provenance.')
    if snapshot.get('directed') is not True or snapshot.get('multigraph') is not False:
        raise ValueError('Expected a directed simple runtime graph.')
    nodes = snapshot.get('nodes')
    edges = snapshot.get('edges')
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError('Runtime snapshot must contain nodes and edges arrays.')
    identifiers = [node['id'] for node in nodes]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError('Duplicate runtime graph node identifiers.')
    identifiers = set(identifiers)
    if any(not node.get('node_type') for node in nodes):
        raise ValueError('Runtime graph contains an untyped node.')
    if any(edge.get('source') not in identifiers or edge.get('target') not in identifiers or not edge.get('edge_type') for edge in edges):
        raise ValueError('Runtime graph contains an unresolved or untyped edge.')
    metadata['snapshot_sha256'] = hashlib.sha256(content).hexdigest()
    metadata['available_ci_tools'] = sorted(RUNTIME_CI_TOOLS)
    return snapshot


def load_runtime_graph(path, expectedInstance):
    import networkx as nx
    snapshot = read_runtime_snapshot(path, expectedInstance)
    graph = nx.DiGraph()
    graph.graph.update(snapshot['graph'])
    graph.add_nodes_from((node['id'], {key: value for key, value in node.items() if key != 'id'}) for node in snapshot['nodes'])
    graph.add_edges_from((edge['source'], edge['target'], {key: value for key, value in edge.items() if key not in {'source', 'target'}}) for edge in snapshot['edges'])
    return graph


def runtime_model_facts(graph, modelName):
    key = 'model:' + modelName
    if key not in graph or graph.nodes[key].get('node_type') != 'Model':
        return {'error': 'Model is absent from the exported scope; no absence or access conclusion is possible.'}
    associated = {key}
    associated.update(target for _, target in graph.out_edges(key)
                      if graph.nodes[target].get('node_type') in {'Field', 'Method', 'Module', 'AccessEntry', 'Rule', 'View'})
    associated.update(node for node, data in graph.nodes(data=True)
                      if data.get('node_type') in {'Button', 'Action'} and (data.get('model') == modelName or data.get('res_model') == modelName))
    for node in list(associated):
        associated.update(target for _, target, attrs in graph.out_edges(node, data=True)
                          if attrs.get('edge_type') == 'APPLIES_TO_GROUP')
    rows = []
    priority = {'Model': 0, 'AccessEntry': 1, 'Rule': 2, 'Group': 3, 'Button': 4, 'Action': 5, 'View': 6}
    for node in sorted(associated, key=lambda item: (priority.get(graph.nodes[item].get('node_type'), 7), item)):
        data = graph.nodes[node]
        row = {'id': node, **{name: data[name] for name in (
            'node_type', 'name', 'description', 'label', 'field_type', 'compute', 'related', 'store',
            'xml_id', 'domain_force', 'active', 'perm_read', 'perm_write', 'perm_create', 'perm_unlink',
            'all_authenticated', 'filepaths', 'source_sites', 'filepath', 'lineno', 'end_lineno', 'override_sites',
            'button_type', 'invisible', 'view_xml_id', 'declaration_only') if name in data}}
        row['relations'] = [{'type': attrs.get('edge_type'), 'target': target}
                            for _, target, attrs in graph.out_edges(node, data=True)
                            if attrs.get('edge_type') in {'APPLIES_TO_GROUP', 'IMPLIES', 'RELATES_TO'}]
        rows.append(row)
    result = {'provenance': {name: graph.graph.get(name) for name in (
        'instance_key', 'exported_at', 'module_scope', 'coverage_gaps', 'limitations', 'snapshot_sha256')},
        'model': modelName, 'fact_count': len(rows), 'facts': rows, 'truncated': False,
        'notice': 'Exported metadata, not a live authorization or approval verdict. Read current source and requester-authorized ORM data when needed.'}
    while len(json.dumps(result, ensure_ascii=False)) > 7000 and result['facts']:
        result['facts'].pop()
        result['truncated'] = True
    return result
