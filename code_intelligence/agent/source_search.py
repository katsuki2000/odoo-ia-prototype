"""Bounded lexical discovery of source fragments evidenced by an instance graph."""

from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import sqlite3
from xml.parsers import expat


@dataclass(frozen=True)
class SearchLimits:
    maxFiles: int = 200
    maxFileBytes: int = 1_000_000
    maxTotalBytes: int = 8_000_000
    maxFragments: int = 4000
    maxLines: int = 200


@dataclass(frozen=True)
class SourceFragment:
    symbol: str
    start: int
    end: int
    text: str
    truncated: bool = False


def python_fragments(text: str, maxLines: int = 200) -> list[SourceFragment]:
    tree = ast.parse(text)
    lines = text.splitlines()
    fragments = []
    def visit(node, parent=''):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            symbol = parent + '.' + node.name if parent else node.name
            start = min([node.lineno, *[item.lineno for item in node.decorator_list]])
            end = min(node.end_lineno, start + maxLines - 1)
            fragments.append(SourceFragment(symbol, start, end, '\n'.join(lines[start - 1:end]),
                                            end < node.end_lineno))
            parent = symbol
        for child in ast.iter_child_nodes(node):
            visit(child, parent)
    visit(tree)
    return fragments


def xml_fragments(text: str, maxLines: int = 200) -> list[SourceFragment]:
    parser = expat.ParserCreate()
    lines = text.splitlines()
    stack, fragments = [], []
    def startElement(name, attributes):
        symbol = ' '.join(str(attributes[key]) for key in ('id', 'name', 'model', 'string') if key in attributes)
        stack.append((name, symbol, parser.CurrentLineNumber))
    def endElement(name):
        tag, symbol, start = stack.pop()
        if tag in {'record', 'button', 'menuitem', 'field', 'template'} and symbol:
            actualEnd = min(parser.CurrentLineNumber, len(lines))
            end = min(actualEnd, start + maxLines - 1)
            fragments.append(SourceFragment(symbol, start, end, '\n'.join(lines[start - 1:end]), end < actualEnd))
    def rejectDoctype(*args):
        raise ValueError('DTD declarations are not supported for source discovery.')
    parser.StartElementHandler = startElement
    parser.EndElementHandler = endElement
    parser.StartDoctypeDeclHandler = rejectDoctype
    parser.ExternalEntityRefHandler = lambda *args: 0
    parser.Parse(text, True)
    return fragments


def graph_source_inventory(graph, model: str = '', module: str = '') -> dict[str, dict]:
    """Collect paths from graph metadata, never by crawling addon directories."""
    inventory = {}
    for nodeId, data in graph.nodes(data=True):
        owner = (data.get('name') or str(nodeId).removeprefix('model:')) if data.get('node_type') == 'Model' else data.get('model', '')
        nodeModule = data.get('module', '')
        sites = [data, *[site for key in ('source_sites', 'override_sites')
                        for site in data.get(key, []) if isinstance(site, dict)]]
        for site in sites:
            siteModule = site.get('module') or nodeModule
            if model and owner != model and model not in data.get('scope_models', []):
                continue
            paths = [site.get('filepath'), *(site.get('filepaths') or [])]
            for value in paths:
                if not isinstance(value, str) or Path(value).suffix.lower() not in {'.py', '.xml'}:
                    continue
                if module and siteModule != module and module not in Path(value).parts:
                    continue
                entry = inventory.setdefault(value, {'models': set(), 'modules': set(),
                                                     'context_models': set(), 'priority': 2})
                entry['context_models'].update(data.get('scope_models', []))
                entry['priority'] = min(entry['priority'], data.get('source_priority', 0))
                if owner:
                    entry['models'].add(owner)
                if siteModule:
                    entry['modules'].add(siteModule)
    return inventory


def confined_source_path(value: str, roots: list[Path]) -> Path | None:
    path = Path(value)
    candidates = [path] if path.is_absolute() else [path, *[root / path for root in roots]]
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
            if (resolved.is_file() and resolved.suffix.lower() in {'.py', '.xml'}
                    and any(root == resolved or root in resolved.parents for root in roots)):
                return resolved
        except (OSError, RuntimeError):
            continue
    return None


def search_source_fragments(graph, roots, query: str, *, model: str = '', module: str = '',
                            limit: int = 8, limits: SearchLimits | None = None) -> dict:
    limits = limits or SearchLimits()
    if any(value <= 0 for value in vars(limits).values()):
        raise ValueError('Source search limits must be positive.')
    roots = [Path(root).resolve() for root in roots if root]
    tokens = list(dict.fromkeys(re.findall(r'[^\W_]+', query.casefold(), re.UNICODE)))[:24]
    coverage = {'files_considered': 0, 'files_indexed': 0, 'fragments_indexed': 0,
                'blocked_paths': 0, 'unreadable_files': 0, 'parse_errors': 0,
                'oversized_files': 0, 'truncated_fragments': 0, 'budget_exhausted': False}
    snapshotGaps = getattr(graph, 'graph', {}).get('coverage_gaps', {})
    coverage['inventory_gaps'] = {key: snapshotGaps[key] for key in (
        'unavailable_module_paths', 'skipped_source_links', 'unavailable_method_sources', 'unavailable_sources')
        if snapshotGaps.get(key)}
    result = {'discovery_only': True, 'candidates': [], 'coverage': coverage,
              'notice': 'Module inventory may include files not loaded by Odoo. Context models indicate scope, not proven ownership or execution. Locations are candidates, not behavior evidence. Read the source before concluding. An empty search is not proof of absence.'}
    if not tokens:
        return result
    inventory = graph_source_inventory(graph, model, module)
    coverage['files_considered'] = len(inventory)
    metadata, visited, totalBytes = [], set(), 0
    with sqlite3.connect(':memory:') as database:
        database.execute('CREATE VIRTUAL TABLE fragments USING fts5(symbol, models, modules, body)')
        for pathText, scope in sorted(inventory.items(), key=lambda item: (item[1]['priority'], item[0])):
            path = confined_source_path(pathText, roots)
            if path is None:
                coverage['blocked_paths'] += 1
                continue
            if path in visited:
                continue
            visited.add(path)
            if coverage['files_indexed'] >= limits.maxFiles or len(metadata) >= limits.maxFragments:
                coverage['budget_exhausted'] = True
                break
            try:
                if path.stat().st_size > limits.maxFileBytes:
                    coverage['oversized_files'] += 1
                    continue
                with path.open('rb') as handle:
                    content = handle.read(limits.maxFileBytes + 1)
                if len(content) > limits.maxFileBytes:
                    coverage['oversized_files'] += 1
                    continue
                totalBytes += len(content)
                if totalBytes > limits.maxTotalBytes:
                    coverage['budget_exhausted'] = True
                    break
                text = content.decode('utf-8-sig')
                fragments = (python_fragments(text, limits.maxLines) if path.suffix.lower() == '.py'
                             else xml_fragments(text, limits.maxLines))
            except (OSError, UnicodeError):
                coverage['unreadable_files'] += 1
                continue
            except (SyntaxError, ValueError, expat.ExpatError, RecursionError):
                coverage['parse_errors'] += 1
                continue
            coverage['files_indexed'] += 1
            digest = hashlib.sha256(content).hexdigest()
            for fragment in fragments:
                if len(metadata) >= limits.maxFragments:
                    coverage['budget_exhausted'] = True
                    break
                models, modules = sorted(scope['models']), sorted(scope['modules'])
                database.execute('INSERT INTO fragments VALUES (?, ?, ?, ?)',
                                 (fragment.symbol, ' '.join(models), ' '.join(modules), fragment.text))
                metadata.append({'filepath': str(path), 'line_start': fragment.start, 'line_end': fragment.end,
                                 'symbol': fragment.symbol, 'models': models, 'modules': modules,
                                 'context_models': sorted(scope['context_models']),
                                 'sha256': digest, 'truncated': fragment.truncated})
                coverage['truncated_fragments'] += int(fragment.truncated)
        expression = ' OR '.join('"' + token + '"' for token in tokens)
        rows = database.execute(
            'SELECT rowid FROM fragments WHERE fragments MATCH ? ORDER BY bm25(fragments, 8, 4, 2, 1), rowid LIMIT ?',
            (expression, max(1, min(int(limit), 20)))).fetchall()
        result['candidates'] = [metadata[rowId - 1] for rowId, in rows]
    coverage['fragments_indexed'] = len(metadata)
    result['complete_scan'] = not coverage['inventory_gaps'] and not any(coverage[key] for key in (
        'blocked_paths', 'unreadable_files', 'parse_errors', 'oversized_files', 'truncated_fragments', 'budget_exhausted'))
    return result
