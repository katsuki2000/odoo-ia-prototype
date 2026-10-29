import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SETTINGS_PATH = Path(__file__).resolve().parents[1] / "odoo_addons/miro_ai/models/miro_ai_settings.py"


class _UserError(Exception):
    pass


@pytest.fixture
def settings_module(monkeypatch):
    odoo = types.ModuleType("odoo")
    odoo.models = types.SimpleNamespace(Model=object)
    odoo.fields = MagicMock()
    odoo.api = MagicMock()
    odoo._ = lambda message, *args: message
    exceptions = types.ModuleType("odoo.exceptions")
    exceptions.UserError = _UserError
    odoo.exceptions = exceptions
    monkeypatch.setitem(sys.modules, "odoo", odoo)
    monkeypatch.setitem(sys.modules, "odoo.exceptions", exceptions)
    spec = importlib.util.spec_from_file_location("miro_ai_settings_under_test", SETTINGS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record(api_token):
    return types.SimpleNamespace(api_token=api_token, ensure_one=lambda: None)


def test_strong_secret_is_returned(settings_module):
    secret = "k" * 40
    assert settings_module.MiroAiSettings.get_signing_secret(_record(secret)) == secret


@pytest.mark.parametrize("token", [False, "", "short", "a" * 31])
def test_missing_or_short_secret_is_refused(settings_module, token):
    with pytest.raises(_UserError):
        settings_module.MiroAiSettings.get_signing_secret(_record(token))


def test_legacy_default_secret_is_refused_even_if_long_enough(settings_module):
    legacy = settings_module.LEGACY_DEFAULT_SECRET
    with pytest.raises(_UserError):
        settings_module.MiroAiSettings.get_signing_secret(_record(legacy))


def test_no_hardcoded_default_secret_remains_in_signing_paths():
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "api/auth.py",
        "odoo_addons/miro_ai/controllers/main.py",
    ):
        assert "default_insecure_secret_for_dev" not in (root / relative).read_text(encoding="utf-8"), relative


def test_signed_tokens_expire_after_five_minutes():
    root = Path(__file__).resolve().parents[1]
    # The Odoo controller issues its token in ask_flow.py through a named constant.
    ask_flow = (root / "odoo_addons/miro_ai/controllers/ask_flow.py").read_text(encoding="utf-8")
    assert "JWT_LIFETIME_SECONDS = 300" in ask_flow
    assert '"exp": int(time.time()) + JWT_LIFETIME_SECONDS' in ask_flow
    for relative in (
        "odoo_addons/miro_ai/controllers/main.py",
        "odoo_addons/miro_ai/controllers/ask_flow.py",
    ):
        assert "+ 3600" not in (root / relative).read_text(encoding="utf-8"), relative


def test_signed_token_carries_the_requester_database():
    root = Path(__file__).resolve().parents[1]
    ask_flow = (root / "odoo_addons/miro_ai/controllers/ask_flow.py").read_text(encoding="utf-8")
    assert '"db": user.env.cr.dbname' in ask_flow


def test_settings_model_not_readable_by_internal_user():
    """Signing config must not be granted to base.group_user (RPC would leak api_token)."""
    root = Path(__file__).resolve().parents[1]
    csv_path = root / "odoo_addons/miro_ai/security/ir.model.access.csv"
    lines = [
        line.strip()
        for line in csv_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("id,")
    ]
    for line in lines:
        parts = line.split(",")
        assert len(parts) >= 7, line
        model_xml_id, group_xml_id, perm_read = parts[2], parts[3], parts[4]
        if model_xml_id != "model_miro_ai_settings":
            continue
        assert group_xml_id != "base.group_user", line
        assert perm_read == "1", line


def test_api_token_field_restricted_to_admin_groups():
    source = (
        Path(__file__).resolve().parents[1]
        / "odoo_addons/miro_ai/models/miro_ai_settings.py"
    ).read_text(encoding="utf-8")
    assert "groups='base.group_system,miro_ai.group_miro_ai_admin'" in source
    assert "copy=False" in source


def test_env_example_documents_jwt_and_cors():
    text = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")
    for key in ("JWT_SECRET=", "API_HOST=", "CORS_ALLOWED_ORIGINS="):
        assert key in text, key
