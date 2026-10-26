"""Search only source files inventoried by the active knowledge graph."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from code_intelligence.agent.text_normalization import strip_accents
from code_intelligence.agent.tools.helpers import _is_custom_module_filepath

_SUPPORTED_SUFFIXES = {'.py', '.xml', '.js', '.csv', '.sql', '.po', '.html', '.scss', '.css'}
_STOPWORDS = frozenset({
    'des', 'les', 'dans', 'par', 'pour', 'avec', 'sur', 'une', 'que', 'qui',
    'est', 'son', 'ses', 'aux', 'the', 'and', 'for', 'with', 'from', 'this',
    'that', 'are', 'was',
})


@dataclass(frozen=True)
class SearchLimits:
    max_files: int = 200
    max_file_bytes: int = 500_000
    max_total_bytes: int = 5_000_000
    max_fragments: int = 20
    max_lines: int = 16

    def validate(self):
        values = (
            self.max_files, self.max_file_bytes, self.max_total_bytes,
            self.max_fragments, self.max_lines,
        )
        if any(type(value) is not int or value < 1 for value in values):
            raise ValueError('Source search limits must be positive integers.')


def _source_inventory(graph):
    inventory = {}
    for nodeId, attributes in graph.nodes(data=True):
        pathModules = {}
        for path in attributes.get('filepaths', []):
            pathModules.setdefault(path, set())
        filepath = attributes.get('filepath')
        if filepath:
            pathModules.setdefault(filepath, set())
        module = attributes.get('module')
        if module:
            for modules in pathModules.values():
                modules.add(module)
        for key in ('override_sites', 'source_sites'):
            for site in attributes.get(key, []):
                if isinstance(site, dict) and site.get('filepath'):
                    siteModule = site.get('module') or module
                    pathModules.setdefault(site['filepath'], set())
                    if siteModule:
                        pathModules[site['filepath']].add(siteModule)
        models = set(attributes.get('context_models', []))
        contextModels = set(attributes.get('scope_models', []))
        if attributes.get('model'):
            models.add(attributes['model'])
        if attributes.get('node_type') == 'Model' and attributes.get('name'):
            models.add(attributes['name'])
        if not module and nodeId.startswith('module:'):
            module = nodeId.removeprefix('module:')
        for path, modules in pathModules.items():
            entry = inventory.setdefault(
                path, {'models': set(), 'context_models': set(), 'modules': set()},
            )
            entry['models'].update(models)
            entry['context_models'].update(contextModels)
            entry['modules'].update(modules)
            if not modules and module:
                entry['modules'].add(module)
    return inventory


def _inside_roots(path, roots):
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return None
    if not resolved.is_file() or not any(
        resolved == root or root in resolved.parents for root in roots
    ):
        return None
    return resolved


def confined_source_path(filepath, roots):
    path = _inside_roots(Path(filepath), [Path(root).resolve() for root in roots])
    if path is None or path.suffix.lower() not in _SUPPORTED_SUFFIXES:
        return None
    return path


def search_source_fragments(
    graph, roots, query, *, model='', module='', limit=8, limits=None, candidate_models=None,
):
    if limit < 1:
        raise ValueError('limit must be positive.')
    limits = limits or SearchLimits()
    limits.validate()
    queryTerms = {
        term for term in re.findall(r'[^\W_]+', strip_accents(query.casefold()))
        if len(term) > 2
    }
    coverage = {
        'files_indexed': 0,
        'parse_errors': 0,
        'oversized_files': 0,
        'blocked_paths': 0,
        'budget_exhausted': False,
    }
    graphMetadata = getattr(graph, 'graph', {})
    coverageGaps = graphMetadata.get('coverage_gaps')
    inventoryVersion = graphMetadata.get('source_file_inventory_version')
    sourceFileInventory = graphMetadata.get('source_file_inventory')
    coverageMetadataValid = (
        inventoryVersion == 1
        and isinstance(sourceFileInventory, list)
        and isinstance(coverageGaps, dict)
    )
    result = {
        'candidates': [],
        'coverage': coverage,
        'coverage_metadata_valid': coverageMetadataValid,
        'coverage_gaps': coverageGaps if isinstance(coverageGaps, dict) else {
            'coverage_metadata_missing_or_stale': True,
        },
        'complete_scan': (
            bool(roots)
            and coverageMetadataValid
            and not any(coverageGaps.values())
        ),
        'discovery_only': True,
    }
    if not queryTerms or not roots:
        result['complete_scan'] = False
        return result

    targetTerms = {term for term in queryTerms if term not in _STOPWORDS} or queryTerms
    pattern = re.compile(
        rf"(?<![a-zA-Z0-9])(?:{'|'.join(re.escape(t) for t in targetTerms)})(?![a-zA-Z0-9])"
    )

    resolvedRoots = [Path(root).resolve() for root in roots if root]
    inventory = _source_inventory(graph)

    # Graph nodes provide precise model/file relations, but not every helper,
    # controller, JS asset or XML file has its own node. Merge the loader's
    # complete per-module source inventory so discovery can search those too.
    modelsByModule = {}
    for nodeId, attributes in graph.nodes(data=True):
        if attributes.get('node_type') != 'Model':
            continue
        modelName = attributes.get('name') or (
            nodeId.removeprefix('model:') if nodeId.startswith('model:') else ''
        )
        if not modelName:
            continue
        for successor in graph.successors(nodeId):
            edge = graph.get_edge_data(nodeId, successor) or {}
            if successor.startswith('module:') and edge.get('edge_type') == 'DEFINED_IN':
                moduleName = successor.removeprefix('module:')
                modelsByModule.setdefault(moduleName, set()).add(modelName)

    sourceEntries = sourceFileInventory if isinstance(sourceFileInventory, list) else []
    for sourceEntry in sourceEntries:
        if not isinstance(sourceEntry, dict):
            continue
        filepath = sourceEntry.get('filepath')
        moduleName = sourceEntry.get('module')
        if not isinstance(filepath, str) or not filepath:
            continue
        entry = inventory.setdefault(
            filepath, {'models': set(), 'context_models': set(), 'modules': set()},
        )
        if isinstance(moduleName, str) and moduleName:
            entry['modules'].add(moduleName)
            entry['context_models'].update(modelsByModule.get(moduleName, set()))

    totalBytes = 0
    candidateSet = set(candidate_models or ())

    def fileSortKey(item):
        filePath, ctx = item
        isCustom = _is_custom_module_filepath(filePath)
        matchesCandidate = bool(candidateSet & (ctx['models'] | ctx['context_models']))
        matchesModule = any(term in m.lower() for m in ctx['modules'] for term in targetTerms)
        matchesFilename = any(term in Path(filePath).name.lower() for term in targetTerms)
        if matchesCandidate and isCustom:
            rank = 0
        elif matchesCandidate:
            rank = 1
        elif (matchesModule or matchesFilename) and isCustom:
            rank = 2
        elif matchesModule or matchesFilename:
            rank = 3
        elif isCustom:
            rank = 4
        else:
            rank = 5
        return (rank, filePath)

    for filepath, context in sorted(inventory.items(), key=fileSortKey):
        if model and model not in context['models'] | context['context_models']:
            continue
        if module and module not in context['modules']:
            continue
        path = _inside_roots(Path(filepath), resolvedRoots)
        if path is None:
            coverage['blocked_paths'] += 1
            result['complete_scan'] = False
            continue
        if path.suffix.lower() not in _SUPPORTED_SUFFIXES:
            continue
        if coverage['files_indexed'] >= limits.max_files:
            coverage['budget_exhausted'] = True
            result['complete_scan'] = False
            break
        try:
            size = path.stat().st_size
            if size > limits.max_file_bytes or totalBytes + size > limits.max_total_bytes:
                coverage['oversized_files'] += 1
                coverage['budget_exhausted'] = True
                result['complete_scan'] = False
                continue
            content = path.read_bytes()
            text = content.decode('utf-8')
        except (OSError, UnicodeDecodeError):
            coverage['parse_errors'] += 1
            result['complete_scan'] = False
            continue
        totalBytes += size
        coverage['files_indexed'] += 1
        normalizedLines = [strip_accents(line.casefold()) for line in text.splitlines()]
        matching = [
            index for index, line in enumerate(normalizedLines)
            if pattern.search(line)
        ]
        if not matching:
            continue
        index = matching[0]
        start = max(0, index - limits.max_lines // 2)
        end = min(len(normalizedLines), start + limits.max_lines)
        result['candidates'].append({
            'filepath': str(path),
            'line_start': start + 1,
            'line_end': end,
            'sha256': hashlib.sha256(content).hexdigest(),
            'models': sorted(context['models']),
            'context_models': sorted(context['context_models']),
            'modules': sorted(context['modules']),
        })
        if len(result['candidates']) >= min(limit, limits.max_fragments):
            result['complete_scan'] = False
            break
    coverage['fragments_indexed'] = len(result['candidates'])
    return result
