"""Read-only structural diagnostics for live and serialized knowledge graphs."""

from collections import Counter


EDGE_TYPES = {
    'EXTENDS': ('Model', 'Model'),
    'DELEGATES_TO': ('Model', 'Model'),
    'RELATES_TO': ('Field', 'Model'),
    'COMPUTED_BY': ('Field', 'Method'),
    'DEPENDS_ON': ('Method', 'Field'),
    'HAS_FIELD': ('Model', 'Field'),
    'HAS_BUTTON': ('Model', 'Button'),
    'DEFINED_IN': ('Model', 'Module'),
    'GRANTED_BY': ('Model', 'AccessEntry'),
    'RESTRICTED_BY': ('Model', 'Rule'),
    'TARGETS_MODEL': ('ServerAction', 'Model'),
    'TRIGGERED_BY': ('AutomationRule', 'Model'),
    'OPENS_MODEL': ('Menu', 'Model'),
    'APPLIES_TO_GROUP': (None, 'Group'),
    'IMPLIES': ('Group', 'Group'),
    'IMPLIES_CONFIGURABLE': ('Group', 'Group'),
    'CHILD_OF': ('Menu', 'Menu'),
    'EXECUTES_ACTION': ('AutomationRule', 'ServerAction'),
    'TRANSITIONS_VIA': ('WorkflowState', 'WorkflowState'),
}


def inspect_graph_structure(nodes, edges):
    """Inspect node attributes and edge triples without inferring missing objects."""
    nodesById = dict(nodes)
    issues = []
    edgeCount = 0
    linkedAcls = set()
    for nodeId, attrs in nodesById.items():
        if not attrs.get('node_type'):
            issues.append({'kind': 'untyped_node', 'node': nodeId})
    for source, target, attrs in edges:
        edgeCount += 1
        edgeType = attrs.get('edge_type')
        if not edgeType:
            issues.append({'kind': 'untyped_edge', 'source': source, 'target': target})
        expectedTypes = EDGE_TYPES.get(edgeType, (None, None))
        for endpoint, nodeId, expectedType in zip(('source', 'target'), (source, target), expectedTypes):
            actualType = nodesById.get(nodeId, {}).get('node_type')
            if nodeId not in nodesById or (expectedType is not None and actualType != expectedType):
                issues.append({'kind': 'unresolved_endpoint', 'source': source, 'target': target,
                               'edge_type': edgeType, 'endpoint': endpoint,
                               'expected_type': expectedType, 'actual_type': actualType})
        if edgeType == 'EXTENDS' and source == target:
            issues.append({'kind': 'self_inheritance', 'node': source})
        if edgeType == 'GRANTED_BY' and nodesById.get(source, {}).get('node_type') == 'Model':
            linkedAcls.add(target)
    for nodeId, attrs in nodesById.items():
        if attrs.get('node_type') == 'AccessEntry' and nodeId not in linkedAcls:
            issues.append({'kind': 'acl_without_model', 'node': nodeId})
    return {'scope': 'static_structure', 'node_count': len(nodesById), 'edge_count': edgeCount,
            'issue_count': len(issues), 'counts': dict(sorted(Counter(issue['kind'] for issue in issues).items())),
            'issues': issues}


def build_graph_integrity_report(graph):
    report = inspect_graph_structure(graph.nodes(data=True), graph.edges(data=True))
    report['unresolved_reference_count'] = len(graph.graph.get('unresolved_references', []))
    return report


def inspect_serialized_graph(payload):
    """Accept current metadata wrappers and legacy NetworkX node-link objects."""
    graphData = payload if 'nodes' in payload else payload.get('graph', payload)
    if not isinstance(graphData, dict) or 'nodes' not in graphData:
        raise ValueError('Expected a node-link graph with a nodes array.')
    nodeRows = graphData['nodes']
    edgeRows = graphData.get('edges', graphData.get('links'))
    if not isinstance(nodeRows, list) or not isinstance(edgeRows, list):
        raise ValueError('Expected node and edge arrays.')
    if any(not isinstance(row, dict) or 'id' not in row for row in nodeRows):
        raise ValueError('Every node must have an id.')
    if any(not isinstance(row, dict) or 'source' not in row or 'target' not in row for row in edgeRows):
        raise ValueError('Every edge must have source and target identifiers.')
    nodeIds = [row['id'] for row in nodeRows]
    if len(set(nodeIds)) != len(nodeIds):
        raise ValueError('Duplicate node identifiers are not supported.')
    report = inspect_graph_structure(
        ((row['id'], row) for row in nodeRows),
        ((row['source'], row['target'], row) for row in edgeRows),
    )
    report['unresolved_reference_count'] = len(graphData.get('graph', {}).get('unresolved_references', []))
    return report
