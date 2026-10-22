import re
from pathlib import Path

def read(p): return Path(p).read_text(encoding='utf-8')
def write(p, c): Path(p).write_text(c, encoding='utf-8')
def sub(path, old, new, count=1):
    c = read(path)
    assert c.count(old) == count, (path, old[:70], c.count(old))
    write(path, c.replace(old, new))

# 1. settings
sub('config/settings.py', "DEFAULT_EMBEDDING_BACKEND = 'local_server'\nEMBEDDING_BACKEND = os.getenv('EMBEDDING_BACKEND', DEFAULT_EMBEDDING_BACKEND).lower()\n", '')

# 2. embedding_functions
p = 'document_rag/vectorstore/embedding_functions.py'
sub(p, "SERVER_EMBEDDING_BACKENDS = frozenset({'local_server', 'ollama', 'openai_compatible', 'vllm'})\n\n\n", "\n")
sub(p, 'class LocalServerEmbeddingFunction(EmbeddingFunction):\n    """HTTP embedding client for configured OpenAI-compatible servers."""',
       'class OllamaEmbeddingFunction(EmbeddingFunction):\n    """HTTP embedding client for the configured Ollama server (OpenAI-compatible API)."""')
sub(p, "    def name(self) -> str:\n        return f'local-server-{self.model}'",
       "    def name(self) -> str:\n        # Persisted in Chroma collections and in the semantic index identity: renaming forces a reindex.\n        return f'local-server-{self.model}'")
c = read(p)
i = c.index('def resolve_embedding_function(')
write(p, c[:i] + '''def resolve_embedding_function(embedding_model: Optional[str] = None) -> EmbeddingFunction:
    """Embedding client for the configured Ollama server; an explicit model overrides the configured one."""
    from config.settings import EMBEDDING_BASE_URL, EMBEDDING_MODEL, EMBEDDING_API_KEY, require_inference_server
    return OllamaEmbeddingFunction(base_url=require_inference_server(EMBEDDING_BASE_URL),
                                   model=embedding_model or EMBEDDING_MODEL,
                                   api_key=EMBEDDING_API_KEY)
''')

# 3. semantic_retrieval
sub('code_intelligence/agent/resolution/semantic_retrieval.py',
"""def build_semantic_embedding_function():
    from config.settings import DEFAULT_EMBEDDING_BACKEND
    from document_rag.vectorstore.embedding_functions import resolve_embedding_function
    backend = (os.getenv('RESOLVER_SEMANTIC_EMBEDDING_BACKEND') or os.getenv('EMBEDDING_BACKEND', DEFAULT_EMBEDDING_BACKEND)).strip().lower()
    model = os.getenv('RESOLVER_SEMANTIC_EMBEDDING_MODEL')
    return resolve_embedding_function(backend=backend, embedding_model=model)
""",
"""def build_semantic_embedding_function():
    from document_rag.vectorstore.embedding_functions import resolve_embedding_function
    return resolve_embedding_function(embedding_model=os.getenv('RESOLVER_SEMANTIC_EMBEDDING_MODEL'))
""")

# 4. turn.py
sub('code_intelligence/agent/resolution/turn.py', "key in {'LLM_TARGET', 'EMBEDDING_BACKEND'}", "key == 'LLM_TARGET'")

# 5. fingerprint
p = 'core/llm/server_fingerprint.py'
sub(p, '        "provider": llm.get("provider"),\n', '')
sub(p, '        "embedding_backend": (fingerprint.get("embedding") or {}).get("backend"),\n', '')
sub(p, '    provider: Optional[str] = None,\n', '')
sub(p, '    embedding_backend: Optional[str] = None,\n', '')
sub(p, '    provider = provider or "ollama"\n', '')
sub(p, '{"provider": provider, "configured_model": model,', '{"configured_model": model,')
sub(p, '            "backend": embedding_backend or settings.EMBEDDING_BACKEND,\n', '')
sub(p, 'if str(provider).lower() == "ollama" and (http_get is not None or not client_injected):', 'if http_get is not None or not client_injected:')

# 6. synthesis bench
p = 'core/evaluation/synthesis_bench.py'
sub(p, 'KNOWN_PROVIDERS = {"ollama", "local", "vllm", "openai_compatible", "lmstudio", "llamacpp"}\n', '')
sub(p, '''    model: str
    provider: Optional[str] = None

    @classmethod
    def parse(cls, raw: str) -> "ModelSpec":
        head, _, tail = raw.partition(":")
        if tail and head.lower() in KNOWN_PROVIDERS:
            return cls(model=tail, provider=head.lower())
        return cls(model=raw)

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}" if self.provider else self.model
''', '''    model: str

    @classmethod
    def parse(cls, raw: str) -> "ModelSpec":
        return cls(model=raw)

    @property
    def label(self) -> str:
        return self.model
''')
sub(p, '            provider=spec.provider, model=spec.model, base_url=base_url,\n', '            model=spec.model, base_url=base_url,\n')
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
