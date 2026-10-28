from pathlib import Path

path = Path('tests/test_rag_model_eval.py')
text = path.read_text(encoding='utf-8')


def swap(old, new):
    global text
    assert text.count(old) == 1, old[:60]
    text = text.replace(old, new)


swap('''import pytest

SCRIPT''', '''import pytest

from core.evaluation import bench_common

SCRIPT''')
swap('''def test_normalize_ignores_case_accents_spaces_and_emphasis(bench):
    assert bench.normalize("**48** Heures\\u202fOuvrées") == bench.normalize("48 heures ouvrees")
    assert bench.normalize("d\\u2019Identification") == bench.normalize("d'identification")


''', '')
swap('''def test_context_length_must_match_the_comparison_configuration(bench):
    bench.require_context_length({"context_length": 32768}, 32768)
    with pytest.raises(bench.BackendUnavailable, match="Expected Ollama context length 32768"):
        bench.require_context_length({"context_length": 4096}, 32768)
    with pytest.raises(bench.BackendUnavailable, match="got None"):
        bench.require_context_length({}, 32768)


''', '')
swap('len(runs) == bench.MAX_CONSECUTIVE_ERRORS', 'len(runs) == bench_common.MAX_CONSECUTIVE_ERRORS')
path.write_text(text, encoding='utf-8')
print('ok')
