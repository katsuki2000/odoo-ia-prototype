"""Discover read-only investigation calls from the installed graph."""

from dataclasses import dataclass
from hashlib import sha256
from itertools import zip_longest
import json
import logging

from .investigation_schemas import PlanAction
from .node_labels import node_labels

logger = logging.getLogger(__name__)
MAX_CANDIDATES = 128


@dataclass(frozen=True)
class Capability:
    action: PlanAction
    target: str
    arguments: dict
    description: str

    @property
    def identifier(self):
        payload = [self.action.value, self.target, self.arguments]
        return sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]


def resolved_targets(graph, concept):
    if graph is None or concept is None or not concept.is_resolved:
        return []
    models = list(concept.resolved_models)
    modules = {'module:' + module for module in concept.resolved_modules}
    if modules:
        models.extend(source.removeprefix('model:') for source, target, edge in graph.edges(data=True)
                      if target in modules and source.startswith('model:')
                      and edge.get('edge_type') == 'DEFINED_IN' and edge.get('role', 'declares') in {'declares', 'extends'})
    return [model for model in dict.fromkeys(models)
            if graph.nodes.get('model:' + model, {}).get('node_type') == 'Model']


def build_capability_catalogue(graph, concept):
    models = resolved_targets(graph, concept)
    if not models:
        return []
    perModel = {model: [] for model in models}

    def add(model, action, arguments, description):
        perModel[model].append(Capability(action, model, arguments, description))

    for model in models:
        data = graph.nodes['model:' + model]
        detail = ' '.join(node_labels(data))
        for action, description in (
            (PlanAction.DESCRIBE_WORKFLOW, 'Inspect recorded workflow states and transitions'),
            (PlanAction.DESCRIBE_NAVIGATION_PATH, 'Locate the model in the installed user interface'),
            (PlanAction.TRACE_FULL_INHERITANCE, 'Inspect declaring modules, extensions and inheritance'),
            (PlanAction.ANALYZE_SERVER_ACTIONS, 'Inspect server actions and automations targeting this model'),
        ):
            add(model, action, {'model_name': model}, f'{description}. {detail}')
        add(model, PlanAction.WHO_HAS_ACCESS_TO, {'model_name': model, 'permission': 'all'},
            f'Inspect CRUD ACL grants; these grants do not establish approval authority. {detail}')
        for permission in ('read', 'write', 'create', 'unlink'):
            add(model, PlanAction.EVALUATE_RECORD_RULES, {'model_name': model, 'permission': permission},
                f'Inspect record-rule restrictions for operation {permission}. {detail}')

    sourceModels = {model for model in models if graph.nodes['model:' + model].get('filepaths')}
    for nodeId, data in graph.nodes(data=True):
        nodeType = data.get('node_type')
        if nodeType not in {'Method', 'Field', 'Button'}:
            continue
        prefix = {'Method': 'method:', 'Field': 'field:', 'Button': 'button:'}[nodeType]
        owner = data.get('model')
        if not owner and nodeId.startswith(prefix):
            owner = nodeId[len(prefix):].rpartition('.')[0]
        if owner not in perModel:
            continue
        canonicalPrefix = prefix + owner + '.'
        name = nodeId[len(canonicalPrefix):] if nodeType in {'Method', 'Field'} and nodeId.startswith(canonicalPrefix) else data.get('name')
        if not isinstance(name, str) or not name:
            continue
        description = f"{owner}.{name.replace('_', ' ')}. {' '.join(node_labels(data))}"
        if data.get('filepath'):
            sourceModels.add(owner)
        if nodeType == 'Field':
            add(owner, PlanAction.FIELD_CHANGE_IMPACT, {'model_name': owner, 'field_name': name},
                'Inspect field triggers and computed dependencies: ' + description)
        elif nodeType == 'Button':
            add(owner, PlanAction.BUTTON_EXECUTION_PATH, {'model_name': owner, 'button_name': name},
                'Inspect the recorded UI button, method and access conditions: ' + description)
        else:
            add(owner, PlanAction.ANALYZE_METHOD_OVERRIDE_CHAIN, {'model_name': owner, 'method_name': name},
                'Inspect the recorded method and its extension chain: ' + description)
            start, end = data.get('lineno'), data.get('end_lineno')
            if (data.get('filepath') and type(start) is int and type(end) is int and 0 < start <= end):
                add(owner, PlanAction.READ_SOURCE_CODE,
                    {'filepath': data['filepath'], 'line_start': start, 'line_end': end},
                    'Read the actual implementation, not an inferred method convention: ' + description)
    for model in models:
        if model in sourceModels:
            add(model, PlanAction.ANALYZE_SECURITY_LOCKS, {'model_name': model}, 'Inspect application guards and Python blocking conditions')
            add(model, PlanAction.ANALYZE_DATA_CONSTRAINTS, {'model_name': model}, 'Inspect SQL constraints and relational field domains')
    return list({item.identifier: item for items in perModel.values() for item in items}.values())


def shortlist_capabilities(question, catalogue):
    ranked = catalogue
    if len(catalogue) > MAX_CANDIDATES:
        try:
            from config.settings import SEMANTIC_INDEX_CACHE_DIR
            from .semantic_index_store import SemanticIndexStore
            from .semantic_retrieval import build_semantic_embedding_function, _build_index, _embedding_name, _query_embedding, _cosine_similarity
            provider = build_semantic_embedding_function()
            if provider is None:
                raise ValueError('No semantic provider')
            store = SemanticIndexStore(SEMANTIC_INDEX_CACHE_DIR, _embedding_name(provider) + '-capabilities-v1') if SEMANTIC_INDEX_CACHE_DIR else None
            documents = [(item.identifier, item.target + ' ' + item.description) for item in catalogue]
            identifiers, vectors = _build_index(documents, provider, store)
            query = _query_embedding(provider, question)
            scores = {identifier: _cosine_similarity(query, vector) for identifier, vector in zip(identifiers, vectors)}
            ranked = sorted(catalogue, key=lambda item: (-scores[item.identifier], item.identifier))
        except Exception as error:
            logger.warning('Capability retrieval unavailable (%s); using a bounded fair inventory.', type(error).__name__)
    groups = {}
    for item in ranked:
        groups.setdefault(item.target, []).append(item)
    fair = [item for row in zip_longest(*groups.values()) for item in row if item is not None]
    return fair[:MAX_CANDIDATES], len(fair) > MAX_CANDIDATES
