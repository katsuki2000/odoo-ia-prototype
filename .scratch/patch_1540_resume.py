import re
from pathlib import Path

def read(p): return Path(p).read_text(encoding='utf-8')
def write(p, c): Path(p).write_text(c, encoding='utf-8')
def sub(path, old, new, count=1):
    c = read(path)
    assert c.count(old) == count, (path, old[:70], c.count(old))
    write(path, c.replace(old, new))
sub('scripts/run_synthesis_model_bench.py', 'help="[provider:]model, repeatable (e.g. ollama:qwen3:14b)."', 'help="Ollama model tag, repeatable (e.g. qwen3:14b)."')
p = 'tests/test_synthesis_bench.py'
c = read(p)
c, n = re.subn(r'def test_model_spec_parse_splits_known_provider_only\(\):\n(?:    .*\n)+',
               'def test_model_spec_keeps_the_ollama_tag_whole():\n    assert ModelSpec.parse("gpt-oss:20b") == ModelSpec(model="gpt-oss:20b")\n', c)
assert n == 1; write(p, c)

# 7. conftest
p = 'conftest.py'
sub(p, 'Embeddings go through the inference server (EMBEDDING_BACKEND=local_server); tests marked', 'Embeddings go through the Ollama server; tests marked')
sub(p, 'def _pin_embedding_backend(monkeypatch):', 'def _disable_semantic_retrieval(monkeypatch):')
sub(p, '    monkeypatch.setenv("EMBEDDING_BACKEND", "local_server")\n', '')

# 8. tests: fingerprint
p = 'tests/test_inference_fingerprint.py'
sub(p, 'fp.get_inference_fingerprint(provider="local", base_url=base_url, model="qwen3:8b",\n                                        embedding_backend="local_server", embedding_model="bge-m3", client=client, **kw)',
       'fp.get_inference_fingerprint(base_url=base_url, model="qwen3:8b",\n                                        embedding_model="bge-m3", client=client, **kw)')
sub(p, 'fp.get_inference_fingerprint(provider="ollama", base_url=base_url, model="qwen3:8b", embedding_backend="local_server",\n                                        embedding_model="bge-m3", client=_Client(), http_get=http_get)',
       'fp.get_inference_fingerprint(base_url=base_url, model="qwen3:8b",\n                                        embedding_model="bge-m3", client=_Client(), http_get=http_get)')

# 9. tests: semantic retrieval
p = 'code_intelligence/tests/test_semantic_retrieval.py'
sub(p, '    monkeypatch.setenv("RESOLVER_SEMANTIC_EMBEDDING_BACKEND", "local_server")\n', '', count=3)
sub(p, 'assert captured == {"backend": "local_server", "embedding_model": None}', 'assert captured == {"embedding_model": None}')

# 10. tests: regressions
p = 'tests/test_resolver_decision_regressions.py'
sub(p, "        self.settings.DEFAULT_EMBEDDING_BACKEND = 'local_server'\n", '')
sub(p, "module.resolve_embedding_function('local_server', 'resolver-specific')", "module.resolve_embedding_function('resolver-specific')")
sub(p, "self.embedding_module().resolve_embedding_function('local_server')", "self.embedding_module().resolve_embedding_function()")
sub(p, "{'EMBEDDING_BACKEND': 'local_server', 'EMBEDDING_MODEL': 'unrelated-local-name'}", "{'EMBEDDING_MODEL': 'unrelated-local-name'}")
c = read(p)
c, n = re.subn(r"    def test_unselected_local_embedding_backends_are_rejected\(self\):\n(?:        .*\n|\n(?=        ))*\n", '', c)
assert n == 1; write(p, c)

# 11. tests: embedding functions
p = 'tests/document_rag/test_embedding_functions.py'
c = read(p)
marker = 'def test_local_server_embedding_function_openai_format'
i = c.index(marker)
head = '''"""Unit tests for the Ollama embedding client and its resolver."""

from unittest.mock import patch, MagicMock
import pytest

from document_rag.vectorstore.embedding_functions import (
    OllamaEmbeddingFunction,
    resolve_embedding_function,
)


def test_resolve_embedding_function_returns_the_configured_server():
    with patch("config.settings.EMBEDDING_BASE_URL", "http://localhost:11434/v1"), \\
         patch("config.settings.EMBEDDING_MODEL", "all-minilm:latest"), \\
         patch("config.settings.EMBEDDING_API_KEY", "ollama"):
        fn = resolve_embedding_function()
        assert isinstance(fn, OllamaEmbeddingFunction)
        assert fn.model == "all-minilm:latest"
        assert fn.endpoint == "http://localhost:11434/v1/embeddings"


def test_resolve_embedding_function_explicit_model_wins():
    with patch("config.settings.EMBEDDING_BASE_URL", "http://localhost:11434/v1"):
        assert resolve_embedding_function(embedding_model="bge-m3").model == "bge-m3"


def test_resolve_embedding_function_without_server_raises():
    with patch("config.settings.EMBEDDING_BASE_URL", ""):
        with pytest.raises(ValueError, match="No inference server configured"):
            resolve_embedding_function()


'''
write(p, head + c[i:])

# 12. README
c = read('README.md')
lines = c.split('\n')
kept = [l for l in lines if not (l.startswith('| `EMBEDDING_BACKEND` |') or l.startswith('| `RESOLVER_SEMANTIC_EMBEDDING_BACKEND` |'))]
assert len(lines) - len(kept) == 2
write('README.md', '\n'.join(kept))

# 13. test_default_embedding_backend -> test_embedding_server_default
write('tests/document_rag/test_default_embedding_backend.py', '''"""Embedding and resolver retrieval use the configured Ollama server."""
from config import settings
from code_intelligence.agent.resolution.semantic_retrieval import build_semantic_embedding_function
from document_rag.vectorstore.embedding_functions import OllamaEmbeddingFunction, resolve_embedding_function


def _configure(monkeypatch):
    monkeypatch.delenv("RESOLVER_SEMANTIC_EMBEDDING_MODEL", raising=False)
    monkeypatch.setattr(settings, "EMBEDDING_BASE_URL", "http://ollama.example:11434/v1")


def test_resolver_uses_the_configured_server(monkeypatch):
    _configure(monkeypatch)
    provider = resolve_embedding_function()
    assert isinstance(provider, OllamaEmbeddingFunction)
    assert provider.endpoint == "http://ollama.example:11434/v1/embeddings"


def test_business_term_retrieval_uses_the_same_server(monkeypatch):
    _configure(monkeypatch)
    assert isinstance(build_semantic_embedding_function(), OllamaEmbeddingFunction)
''')

# 14. .env : lignes mortes
p = '.env'
dead = re.compile(r'^(LLM_PROVIDER|LOCAL_ALLOWED_HOSTS|LOCAL_LLM_[A-Z_]+|LOCAL_EMBEDDING_[A-Z_]+|EMBEDDING_BACKEND|RESOLVER_SEMANTIC_EMBEDDING_BACKEND|OLLAMA_HOST|OLLAMA_MODEL)=')
out, removed = [], []
for line in read(p).split('\n'):
    m = dead.match(line)
    (removed if m else out).append(m.group(1) if m else line)
write(p, '\n'.join(out))
print('env: lignes retirees ->', removed)
print('ok')
