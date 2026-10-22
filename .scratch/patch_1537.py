from pathlib import Path

def sub(path, old, new, count=1):
    p = Path(path)
    c = p.read_text(encoding='utf-8')
    assert c.count(old) == count, (path, old[:50], c.count(old))
    p.write_text(c.replace(old, new), encoding='utf-8')

# 1. local_only.py : ne garde que le controle du fournisseur
Path('core/llm/local_only.py').write_text('''"""Local-only guard: refuses cloud inference providers while LOCAL_ONLY is enabled.

The inference server address is whatever `config/settings.py` / `.env` configure: no second host list.
"""

from config.settings import LOCAL_ONLY

LOCAL_PROVIDERS = frozenset({"local", "ollama", "vllm", "openai_compatible", "lmstudio", "llamacpp"})


class ExternalEndpointError(ValueError):
    """Raised when LOCAL_ONLY forbids the requested provider."""


def assert_local_provider(provider: str) -> None:
    if LOCAL_ONLY and provider not in LOCAL_PROVIDERS:
        raise ExternalEndpointError(
            f"Provider {provider!r} is not an approved local provider while LOCAL_ONLY is enabled."
        )


__all__ = [
    "LOCAL_PROVIDERS",
    "ExternalEndpointError",
    "assert_local_provider",
]
''', encoding='utf-8')

# 2. llm_client.py
sub('core/llm/llm_client.py', 'from core.llm.local_only import assert_local_endpoint\n', '')
sub('core/llm/llm_client.py', '        assert_local_endpoint(local_base_url, "LLM")\n', '')

# 3. embedding_functions.py
sub('document_rag/vectorstore/embedding_functions.py', 'from core.llm.local_only import assert_local_endpoint\n', '')
sub('document_rag/vectorstore/embedding_functions.py', "        assert_local_endpoint(base_url, 'Embedding')\n", '')

# 4. settings.py
sub('config/settings.py', "LOCAL_ALLOWED_HOSTS = frozenset(host.strip().lower() for host in os.getenv(\n    'LOCAL_ALLOWED_HOSTS', 'localhost,127.0.0.1,::1').split(',') if host.strip())\n", '')

# 5. test stub
sub('tests/test_resolver_decision_regressions.py',
    "'EmbeddingFunction': object, 'Documents': list, 'Embeddings': list,\n            'assert_local_endpoint': lambda *_args: None})",
    "'EmbeddingFunction': object, 'Documents': list, 'Embeddings': list})")

# 6. .env.example
sub('.env.example', '# Un hote distant doit aussi etre autorise dans LOCAL_ALLOWED_HOSTS (ci-dessous).\n', '')
sub('.env.example', "# Hotes distants autorises par la garde LOCAL_ONLY (defaut : localhost,127.0.0.1,::1).\n# LOCAL_ALLOWED_HOSTS=localhost,127.0.0.1,::1,<hote-du-serveur>\n\n", '')

# 7. README
sub('README.md', "For a remote server add its address to `.env` and its host to `LOCAL_ALLOWED_HOSTS`:", "For a remote server add its address to `.env`:")
sub('README.md', "LOCAL_ALLOWED_HOSTS=localhost,127.0.0.1,::1,<aws-instance-address>\n", '')

# 8. notebook (texte brut, mise en forme JSON conservee)
sub('scripts/kaggle/llmodoo.ipynb', '    "LOCAL_ALLOWED_HOSTS=localhost,127.0.0.1,::1,<HOTE_DU_TUNNEL>",\n', '')
sub('scripts/kaggle/llmodoo.ipynb', 'mettre a jour les trois valeurs', 'mettre a jour les deux valeurs')
print('ok')
