import json, time
from pathlib import Path
import networkx as nx

raw = json.loads(Path('active_graph.json').read_text(encoding='utf-8'))
graph = nx.node_link_graph(raw['graph'], edges='edges')

from code_intelligence.agent.tools.helpers import find_model_source_filepaths, model_lineage
from code_intelligence.rules.data_constraints import analyze_data_constraints_from_filepaths, run_semgrep_analysis

config = Path('code_intelligence/semgrep_rules')
for model in ('sale.order', 'account.move'):
    existing = [Path(p) for p in sorted(find_model_source_filepaths(graph, model)) if Path(p).exists()]
    print(f'\n{model}: {len(existing)} files, lineage size {len(model_lineage(graph, model))}', flush=True)
    sample = existing[:8]
    started = time.perf_counter()
    for p in sample:
        run_semgrep_analysis([p], config)
    per_file = (time.perf_counter() - started) / len(sample)
    print(f'  one process per file: {per_file:.2f}s/file -> about {per_file * len(existing):.0f}s for {len(existing)} files', flush=True)
    started = time.perf_counter()
    unfiltered = analyze_data_constraints_from_filepaths(model, [str(p) for p in existing])
    print(f'  one process, all files, no filter: {time.perf_counter() - started:.1f}s, {len(unfiltered.matches)} matches, summary {len(unfiltered.summary_text)} chars', flush=True)
    filtered = analyze_data_constraints_from_filepaths(model, [str(p) for p in existing], relevant_models=model_lineage(graph, model))
    print(f'  with model filter: {len(filtered.matches)} matches, summary {len(filtered.summary_text)} chars', flush=True)
