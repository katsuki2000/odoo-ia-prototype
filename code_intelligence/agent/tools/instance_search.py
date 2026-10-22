"""Find likely Odoo models using the active instance graph."""

from code_intelligence.agent.resolution.matching import _fuzzy_match_graph
from code_intelligence.agent.text_normalization import strip_accents


def find_instance_candidates(graph, query, *, model='', limit=8):
    if not query.strip() or limit < 1:
        return {'semantic_status': 'not_run', 'candidates': []}
    if model and not graph.has_node(f'model:{model}'):
        model = ''
    matches = _fuzzy_match_graph(query, graph, threshold=60, limit=max(limit, 5))
    candidates = []
    for candidate, score in matches:
        if model and candidate != model:
            continue
        attributes = graph.nodes[f'model:{candidate}']
        labels = [
            str(item.get('label', '')).strip()[:160]
            for item in attributes.get('business_labels', [])
            if isinstance(item, dict) and item.get('label')
        ]
        labels = labels[:3]
        description = str(attributes.get('description', '')).strip()[:160]
        if description and description not in labels:
            labels.append(description)
        candidates.append({
            'node_id': f'model:{candidate}',
            'model': candidate,
            'score': score,
            'labels': labels,
        })
    return {'semantic_status': 'not_run', 'candidates': candidates[:limit]}
