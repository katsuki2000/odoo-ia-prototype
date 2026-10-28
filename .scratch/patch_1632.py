from pathlib import Path


def edit(path, pairs):
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    for old, new in pairs:
        assert text.count(old) == 1, (path, old[:70])
        text = text.replace(old, new)
    p.write_text(text, encoding="utf-8")


edit("config/settings.py", [
    ("import os\nimport sys\n", "import os\n"),
    ("# Kaggle is a temporary dev host: delete its entry (and the KAGGLE_* variables) to drop it.\n",
     "# The default target reads unprefixed variables (OLLAMA_HOST, ...); kaggle, a temporary dev host, reads KAGGLE_*:\n"
     "# delete its entry to drop it.\n"),
    ("    'aws': {'prefix': 'AWS', 'headers': {}},\n    'kaggle': {'prefix': 'KAGGLE', 'headers':",
     "    'aws': {'prefix': '', 'headers': {}},\n    'kaggle': {'prefix': 'KAGGLE_', 'headers':"),
    ("os.getenv(f'{LLM_TARGET_PREFIX}_{name}')", "os.getenv(f'{LLM_TARGET_PREFIX}{name}')"),
    ("set {LLM_TARGET_PREFIX}_OLLAMA_HOST in .env.", "set {LLM_TARGET_PREFIX}OLLAMA_HOST in .env."),
    ("LLM_INTERACTIVE_MAX_RETRIES = 1\n", ""),
    ("SENSITIVE_EVIDENCE_GROUP_XMLIDS = frozenset()\n", ""),
    ("_conf_for_addon_paths = (os.getenv('ODOO_CONF_PATH') or os.getenv('EVAL_ODOO_CONF') or os.getenv('ODOO_RC')\n"
     "                         or (str(_default_odoo_conf) if _default_odoo_conf.is_file() else None))\n"
     "_ADDON_PATHS = resolve_addon_paths(_conf_for_addon_paths, os.environ, _default_odoo_root, _ROOT)\n",
     "_ODOO_CONF = (os.getenv('ODOO_CONF_PATH') or os.getenv('ODOO_RC')\n"
     "              or (str(_default_odoo_conf) if _default_odoo_conf.is_file() else None))\n"
     "_ADDON_PATHS = resolve_addon_paths(_ODOO_CONF, os.environ, _default_odoo_root, _ROOT)\n"),
    ("CUSTOM_ADDONS_PATHS = _ADDON_PATHS.custom\n", ""),
    ("_ODOO_ROOT = Path(CORE_ADDONS_PATH).parent\n"
     "_ODOO_VENV_PYTHON = _ODOO_ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')\n"
     "_ODOO_DEFAULT_CONF = _ODOO_ROOT / 'odoo.conf'\n"
     "EVAL_ODOO_BIN = os.getenv('EVAL_ODOO_BIN') or str(_ODOO_ROOT / 'odoo-bin')\n"
     "EVAL_ODOO_PYTHON = os.getenv('EVAL_ODOO_PYTHON') or (str(_ODOO_VENV_PYTHON) if _ODOO_VENV_PYTHON.is_file() else sys.executable)\n"
     "EVAL_ODOO_CONF = os.getenv('EVAL_ODOO_CONF') or (str(_ODOO_DEFAULT_CONF) if _ODOO_DEFAULT_CONF.is_file() else None)\n"
     "ODOO_CONF_PATH = os.getenv('ODOO_CONF_PATH') or os.getenv('EVAL_ODOO_CONF') or os.getenv('ODOO_RC') or EVAL_ODOO_CONF\n"
     "ODOO_DB_DEFAULT, _odoo_db_source = resolve_database(ODOO_CONF_PATH, os.environ)\n"
     "ODOO_URL_DEFAULT, _odoo_url_source = resolve_odoo_url(ODOO_CONF_PATH, os.environ)\n",
     "ODOO_DB_DEFAULT, _odoo_db_source = resolve_database(_ODOO_CONF, os.environ)\n"
     "ODOO_URL_DEFAULT, _odoo_url_source = resolve_odoo_url(_ODOO_CONF, os.environ)\n"),
    ("EVAL_DB_PREFIX = 'eval_'\n"
     "EVAL_INSTANCE_ADMIN_PASSWORD = os.getenv('EVAL_INSTANCE_ADMIN_PASSWORD', 'admin')\n"
     "EVAL_INSTANCES_DIR = str(_ROOT / 'captures' / 'eval_instances')\n"
     "EVAL_OCA_ADDONS_PATH = os.getenv('EVAL_OCA_ADDONS_PATH') or None\n"
     "GRAPH_CACHE_PATH = os.getenv('GRAPH_CACHE_PATH') or str(_ROOT / 'active_graph.json')\n"
     "GRAPH_TRANSLATION_LANGUAGES = ('en_US', 'fr_FR')\n"
     "SEMANTIC_INDEX_CACHE_DIR = str(_ROOT / 'active_semantic_index')\n", ""),
    ("CORE_FRAMEWORK_ADDONS_PATH = _ADDON_PATHS.framework\n"
     "SOURCE_LINK_ROOTS = tuple(str(path) for path in (CORE_ADDONS_PATH, CORE_FRAMEWORK_ADDONS_PATH, *CUSTOM_ADDONS_PATHS) if path)\n", ""),
    ("LATENCY_BUDGET_P90_SECONDS = 12.0\n", ""),
    ("SEMGREP_TIMEOUT_SECONDS = 120\n", ""),
    ("RESOLVER_SEMANTIC_RETRIEVAL_ENABLED = True\n"
     "# Bump to invalidate every persisted resolver semantic index (part of the provider identity).\n"
     "RESOLVER_SEMANTIC_EMBEDDING_REVISION = ''\n", ""),
])

edit("conftest.py", [
    ("import os\n\nimport pytest", "import pytest"),
    ('@pytest.fixture(autouse=True)\ndef _disable_semantic_retrieval(monkeypatch):\n'
     '    if os.environ.get("USE_REMOTE_EMBEDDINGS", "").lower() == "true":\n        return\n'
     '    from config import settings\n    monkeypatch.setattr(settings, "RESOLVER_SEMANTIC_RETRIEVAL_ENABLED", False)\n\n\n'
     '@pytest.fixture(autouse=True)\ndef _isolate_semantic_index_cache(monkeypatch, tmp_path):\n'
     '    from config import settings\n\n'
     '    monkeypatch.setattr(settings, "SEMANTIC_INDEX_CACHE_DIR", str(tmp_path / "semantic_index"))\n\n\n', ""),
])

edit(".env.example", [
    ("# AWS_LLM_API_KEY=\n# AWS_EMBEDDING_API_KEY=\n", "# LLM_API_KEY=\n# EMBEDDING_API_KEY=\n"),
    ("# Chaque variable est lue avec le prefixe de la cible (AWS_ / KAGGLE_), sans repli ni serveur implicite.\n",
     "# La cible aws lit les variables sans prefixe ; kaggle lit les variables KAGGLE_*. Aucun serveur implicite.\n"),
])
edit("README.md", [
    ("AWS_OLLAMA_HOST=http://<aws-instance-address>:11434", "OLLAMA_HOST=http://<aws-instance-address>:11434"),
    ("| `<TARGET>_OLLAMA_HOST` | Yes | none | Ollama server address, read with the prefix of the target (`AWS_` or `KAGGLE_`) |\n"
     "| `<TARGET>_LLM_BASE_URL` / `<TARGET>_LLM_API_KEY` | No | `<host>/v1` / `ollama` | Optional overrides of the chat endpoint and its key |\n"
     "| `<TARGET>_EMBEDDING_BASE_URL` | No | `<host>/v1` | Embedding server URL |\n",
     "| `OLLAMA_HOST` | Yes | none | Ollama server address (`KAGGLE_OLLAMA_HOST` when `LLM_TARGET=kaggle`; every inference variable takes the `KAGGLE_` prefix on that target) |\n"
     "| `LLM_BASE_URL` / `LLM_API_KEY` | No | `<host>/v1` / `ollama` | Optional overrides of the chat endpoint and its key |\n"
     "| `EMBEDDING_BASE_URL` | No | `<host>/v1` | Embedding server URL |\n"),
    ("check `<TARGET>_OLLAMA_HOST` |", "check `OLLAMA_HOST` |"),
])

edit("tests/test_llm_target_settings.py", [
    ("TARGET_VARIABLES = ('LLM_TARGET',)\n",
     "TARGET_VARIABLES = ('LLM_TARGET', 'OLLAMA_HOST', 'LLM_BASE_URL', 'LLM_API_KEY', 'EMBEDDING_BASE_URL', 'EMBEDDING_API_KEY')\n"),
    ("if key not in TARGET_VARIABLES and not key.startswith(('AWS_', 'KAGGLE_'))}", "if key not in TARGET_VARIABLES and not key.startswith('KAGGLE_')}"),
    ("def test_aws_variables_drive_llm_and_embeddings():\n    values = load_settings({'AWS_OLLAMA_HOST':",
     "def test_ollama_host_drives_llm_and_embeddings():\n    values = load_settings({'OLLAMA_HOST':"),
    ("def test_unprefixed_variables_are_ignored():\n    values = load_settings({'OLLAMA_HOST': 'http://generic:11434', 'LLM_MODEL': 'generic-model'})\n    assert values['LLM_BASE_URL'] == ''\n    assert values['LLM_MODEL'] == 'qwen3:14b'\n",
     "def test_default_target_ignores_kaggle_variables():\n    values = load_settings({'KAGGLE_OLLAMA_HOST': 'https://tunnel.example'})\n    assert values['LLM_BASE_URL'] == ''\n"),
    ("load_settings({'AWS_LLM_MODEL': 'from-aws', 'AWS_OLLAMA_MODEL': 'from-aws', 'AWS_EMBEDDING_MODEL': 'from-aws'})",
     "load_settings({'LLM_MODEL': 'from-env', 'OLLAMA_MODEL': 'from-env', 'EMBEDDING_MODEL': 'from-env'})"),
    ("                            'AWS_OLLAMA_HOST': 'https://llm.internal:11434'})", "                            'OLLAMA_HOST': 'https://llm.internal:11434'})"),
])
