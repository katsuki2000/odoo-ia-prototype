import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def edit(path, exact=(), regex=()):
    file = ROOT / path
    text = file.read_text()
    for old, new, *count in exact:
        expected = count[0] if count else 1
        found = text.count(old)
        assert found == expected, f'{path}: expected {expected} match, found {found}: {old[:70]!r}'
        text = text.replace(old, new)
    for pattern, new, *flags in regex:
        text, found = re.subn(pattern, new, text, flags=flags[0] if flags else 0)
        assert found == 1, f'{path}: regex matched {found} times: {pattern[:70]!r}'
    file.write_text(text)


edit('config/settings.py', exact=[
    ("USE_RERANKER = os.getenv('USE_RERANKER', 'false').lower() in ('true', '1', 'yes')\n", ''),
    ("OCA_SAMPLE_ADDONS_PATH = os.getenv('OCA_SAMPLE_ADDONS_PATH') or None\n", ''),
    ("EVAL_INSTANCES_DIR = os.getenv('EVAL_INSTANCES_DIR') or str(_ROOT / 'captures' / 'eval_instances')\n",
     "EVAL_INSTANCES_DIR = os.getenv('EVAL_INSTANCES_DIR') or str(_ROOT / 'captures' / 'eval_instances')\n"
     "EVAL_OCA_ADDONS_PATH = os.getenv('EVAL_OCA_ADDONS_PATH') or None\n"),
])

search_ranking = ROOT / 'document_rag/vectorstore/search_ranking.py'
text = search_ranking.read_text()
text = text[:text.index('def _get_cross_encoder')].rstrip('\n') + '\n'
for old, new in [
    ('Ranking and Fusion Module — Reciprocal Rank Fusion (RRF) & Cross-Encoder Re-ranking.',
     'Ranking and Fusion Module — Reciprocal Rank Fusion (RRF).'),
    ('import logging\nimport sys\nfrom typing import Any\n\nlogger = logging.getLogger(__name__)\n\n'
     '_cross_encoder_model_name = "cross-encoder/ms-marco-MiniLM-L-6-v2"\n_cross_encoder_instance = None\n',
     'from typing import Any\n'),
]:
    assert text.count(old) == 1, old[:60]
    text = text.replace(old, new)
search_ranking.write_text(text)

edit('document_rag/vectorstore/search.py', exact=[
    ('from config.settings import USE_RERANKER, VECTOR_SIMILARITY_FLOOR\n',
     'from config.settings import VECTOR_SIMILARITY_FLOOR\n'),
    ('from document_rag.vectorstore.search_ranking import (\n'
     '    _cross_encoder_model_name, _get_cross_encoder, cross_encoder_rerank, reciprocal_rank_fusion,\n)\n',
     'from document_rag.vectorstore.search_ranking import reciprocal_rank_fusion\n'),
    ('    if use_reranker and len(fused_results) > 1:\n'
     '        final_results = cross_encoder_rerank(query, fused_results, top_k=top_k)\n'
     '    else:\n'
     '        final_results = fused_results[:top_k]\n'
     '    final_results = expand_contiguous_chunks(final_results, chroma_manager=chroma_manager)\n',
     '    final_results = expand_contiguous_chunks(fused_results[:top_k], chroma_manager=chroma_manager)\n'),
    ("'score': top1.get('cross_encoder_score', top1.get('rrf_score', top1.get('score'))),",
     "'score': top1.get('rrf_score', top1.get('score')),"),
    ("'candidate_count_before_rerank': len(fused_results),\n"
     "                                'final_count': len(final_results), "
     "'reranker_used': bool(use_reranker and len(fused_results) > 1),\n",
     "'fused_count': len(fused_results),\n"
     "                                'final_count': len(final_results),\n"),
    ("'score': item.get('cross_encoder_score', item.get('rrf_score', item.get('score'))),\n"
     "                                     'score_type': 'cross_encoder' if 'cross_encoder_score' in item "
     "else 'rrf' if 'rrf_score' in item else 'raw',\n",
     "'score': item.get('rrf_score', item.get('score')),\n"
     "                                     'score_type': 'rrf' if 'rrf_score' in item else 'raw',\n"),
    ("           'cross_encoder_rerank', '_get_cross_encoder', '_cross_encoder_model_name', 'hybrid_search', 'retrieve',\n"
     "           'get_retriever', 'quick_retrieve']",
     "           'hybrid_search', 'retrieve', 'get_retriever', 'quick_retrieve']"),
], regex=[
    (r',\n(\s+)use_reranker: bool = USE_RERANKER, where:', r',\n\1where:'),
])

edit('core/graph/graph_nodes.py', exact=[
    ('from config.settings import USE_RERANKER\n', ''),
    ('chroma_manager=chromaManager, bm25_index=bm25Index, use_reranker=USE_RERANKER)',
     'chroma_manager=chromaManager, bm25_index=bm25Index)'),
])

edit('document_rag/google_drive_usage.md', exact=[
    ('before reranking and after contiguous expansion', 'before and after contiguous expansion'),
])

edit('code_intelligence/graph/loader.py', exact=[
    ('        OCA_SAMPLE_ADDONS_PATH,\n        ODOO_CONF_PATH,\n', '        ODOO_CONF_PATH,\n'),
    ('    for mod_name in custom_modules + oca_modules_loaded:\n', '    for mod_name in custom_modules:\n'),
    ('    if oca_modules_loaded:\n        source_paths.append(Path(OCA_SAMPLE_ADDONS_PATH))\n', ''),
    ('    # 5. Load Direct Dependencies\n', '    # 3. Load Direct Dependencies\n'),
    ('    # 6. Build and Cache Graph\n', '    # 4. Build and Cache Graph\n'),
], regex=[
    (r'    # 4\. Load OCA Sample Modules \(Bloc P3\.1\)\n.*?(?=    # 3\. Load Direct Dependencies\n)', '', re.S),
])

edit('code_intelligence/agent/tools/introspection.py', exact=[
    ('    from config.settings import (\n'
     '        CORE_ADDONS_PATH, CORE_FRAMEWORK_ADDONS_PATH, CUSTOM_ADDONS_PATH, CUSTOM_ADDONS_PATHS,\n'
     '        OCA_SAMPLE_ADDONS_PATH,\n    )\n',
     '    from config.settings import CORE_ADDONS_PATH, CORE_FRAMEWORK_ADDONS_PATH, CUSTOM_ADDONS_PATH, CUSTOM_ADDONS_PATHS\n'),
    ('        CORE_ADDONS_PATH, CORE_FRAMEWORK_ADDONS_PATH, CUSTOM_ADDONS_PATH, *CUSTOM_ADDONS_PATHS,\n'
     '        OCA_SAMPLE_ADDONS_PATH, *graphRoots,\n',
     '        CORE_ADDONS_PATH, CORE_FRAMEWORK_ADDONS_PATH, CUSTOM_ADDONS_PATH, *CUSTOM_ADDONS_PATHS, *graphRoots,\n'),
    ('        from config.settings import (\n'
     '            _ROOT, CORE_ADDONS_PATH, CUSTOM_ADDONS_PATH, CUSTOM_ADDONS_PATHS, OCA_SAMPLE_ADDONS_PATH,\n        )\n',
     '        from config.settings import _ROOT, CORE_ADDONS_PATH, CUSTOM_ADDONS_PATH, CUSTOM_ADDONS_PATHS\n'),
    ('            Path(OCA_SAMPLE_ADDONS_PATH) / filepath_str if OCA_SAMPLE_ADDONS_PATH else None,\n', ''),
    ('                    Path(OCA_SAMPLE_ADDONS_PATH) if OCA_SAMPLE_ADDONS_PATH else None,\n', ''),
])

edit('code_intelligence/rules/structure.py', exact=[
    ('from config.settings import CORE_ADDONS_PATH, CUSTOM_ADDONS_PATH, OCA_SAMPLE_ADDONS_PATH, _ROOT',
     'from config.settings import CORE_ADDONS_PATH, CUSTOM_ADDONS_PATH, _ROOT'),
    ('        Path(OCA_SAMPLE_ADDONS_PATH) / filepath_str if OCA_SAMPLE_ADDONS_PATH else None,\n', ''),
])

edit('core/evaluation/instances/environment.py', exact=[
    ('oca_root=settings.OCA_SAMPLE_ADDONS_PATH,', 'oca_root=settings.EVAL_OCA_ADDONS_PATH,'),
])

edit('scripts/run_bloc_n1_benchmark.py', exact=[
    ("technique, libelles de l'interface Odoo : todo/architecture.md). Une banque\n"
     "dont `meta.requires_setting` n'est pas configure est sautee avec un message.\n",
     "technique, libelles de l'interface Odoo : todo/architecture.md). Les questions\n"
     "dont un module requis n'est pas installe sont sautees avec un message.\n"),
    ('def _unmet_requirement(meta):\n'
     '    setting = meta.get("requires_setting")\n'
     '    if setting and not getattr(settings, setting, None):\n'
     '        return f"setting {setting} is not configured"\n'
     '    return None\n\n\n', ''),
    ('        reason = _unmet_requirement(data["meta"])\n'
     '        if reason:\n'
     '            print(f"[SKIP] Banque \'{name}\' sautee : {reason}.")\n'
     '            continue\n', ''),
])

edit('tests/oca_p3_1_question_bank.json', regex=[
    (r'\n\s*"requires_setting": "OCA_SAMPLE_ADDONS_PATH",', ''),
])

edit('.github/workflows/ci.yml', exact=[
    ('      OCA_SAMPLE_ADDONS_PATH: ${{ github.workspace }}/tests/oca_sample\n', ''),
])

edit('tests/document_rag/test_search.py', exact=[
    ('    cross_encoder_rerank,\n', ''),
    ('        self.assertTrue(len(results) > 0)\n        # Without reranker, results should have rrf_score\n',
     '        self.assertTrue(len(results) > 0)\n'),
    ('    def test_pipeline_without_reranker(self):', '    def test_pipeline_returns_rrf_scores(self):'),
    ('            use_reranker=False,\n', '', 3),
], regex=[
    (r'class TestCrossEncoderRerank\(unittest\.TestCase\):.*?(?=@pytest\.mark\.embedding_server\nclass TestRetrievePipeline)',
     '', re.S),
    (r'    def test_full_pipeline\(self\):\n        with patch\(.*?use_reranker=True,\n            \)\n',
     '    def test_full_pipeline(self):\n'
     '        results = retrieve(\n'
     '            "Comment créer une facture ?",\n'
     '            top_k=3,\n'
     '            chroma_manager=self.chroma,\n'
     '        )\n', re.S),
])

edit('tests/eval_retrieval.py', exact=[
    ('    top_k: int = 5,\n    use_reranker: bool = True,\n) -> dict:', '    top_k: int = 5,\n) -> dict:'),
    ('        use_reranker: Whether to use cross-encoder\n', ''),
    ('                bm25_index=bm25_index,\n                use_reranker=use_reranker,\n            )',
     '                bm25_index=bm25_index,\n            )'),
    ('        "use_reranker": use_reranker,\n', ''),
    ("        f\"| Cross-encoder | `{config.get('cross_encoder', 'ms-marco-MiniLM-L-6-v2')}` |\",\n", ''),
    ("        f\"| Re-ranker enabled | {results['use_reranker']} |\",\n", ''),
    ('        "cross_encoder": "cross-encoder/ms-marco-MiniLM-L-6-v2",\n', ''),
    ('    logger.info(f"Running evaluation (reranker enabled: {use_reranker})...")\n'
     '    results = evaluate_recall(\n'
     '        questions, chroma, bm25,\n'
     '        top_k=5,\n'
     '        use_reranker=use_reranker,\n'
     '    )\n',
     '    logger.info("Running evaluation...")\n'
     '    results = evaluate_recall(questions, chroma, bm25, top_k=5)\n'),
], regex=[
    (r'    use_reranker = "--reranker" in sys\.argv or .*\n', ''),
])

edit('tests/eval_routing_accuracy.py', exact=[
    ('"""Benchmark routing accuracy; cross-encoder reranking is opt-in via RERANK=1."""', '"""Benchmark routing accuracy."""'),
    ('import os\n', ''),
    ('logging.basicConfig(level=logging.WARNING)\n\nUSE_RERANKER = os.environ.get("RERANK") == "1"\n',
     'logging.basicConfig(level=logging.WARNING)\n'),
    ("""    print(f"Testing {total} questions for routing accuracy (reranker={'on' if USE_RERANKER else 'off, fast mode'})...\\n")""",
     '    print(f"Testing {total} questions for routing accuracy...\\n")'),
    ('            # 1. Retrieve (reranker skipped by default -- see module docstring)\n', '            # 1. Retrieve\n'),
    ('                bm25_index=bm25_index,\n                use_reranker=USE_RERANKER,\n            )',
     '                bm25_index=bm25_index,\n            )'),
])

edit('tests/test_e2e_watcher_rag.py', exact=[
    ('bm25_index=None, use_reranker=True, where=None:', 'bm25_index=None, where=None:', 2),
])

edit('tests/test_evidence_first_cleanup.py', exact=[
    ("'search_retrieve': search, 'USE_RERANKER': False})", "'search_retrieve': search})"),
])

edit('tests/test_bloc_n1_question_wording.py', exact=[
    ('def test_banks_are_discovered_and_ids_are_unique(monkeypatch):\n'
     '    monkeypatch.setattr(runner.settings, "OCA_SAMPLE_ADDONS_PATH", "/any", raising=False)\n',
     'def test_banks_are_discovered_and_ids_are_unique():\n'),
], regex=[
    (r'def test_bank_with_unmet_requirement_is_skipped\(monkeypatch\):.*?(?=def test_filters_select_by_id_module_and_bank)',
     '', re.S),
])

edit('code_intelligence/tests/test_audit_regressions.py', exact=[
    ('    monkeypatch.setattr(settings, "OCA_SAMPLE_ADDONS_PATH", None)\n', ''),
])

requirements = ROOT / 'requirements.txt'
dropped = {'sentence-transformers', 'torch', 'transformers', 'safetensors', 'scikit-learn', 'scipy', 'joblib',
           'threadpoolctl', 'sympy', 'mpmath', 'narwhals'}
kept, removed = [], []
for line in requirements.read_text().splitlines():
    name = re.split(r'[=<>~! ;\[]', line, maxsplit=1)[0].strip().lower().replace('_', '-')
    if line.startswith('--extra-index-url https://download.pytorch.org') or name in dropped:
        removed.append(line)
    else:
        kept.append(line)
assert len(removed) == len(dropped) + 1, f'unexpected requirement lines removed: {removed}'
requirements.write_text('\n'.join(kept) + '\n')
print('requirements removed:', removed)
print('patch OK')
