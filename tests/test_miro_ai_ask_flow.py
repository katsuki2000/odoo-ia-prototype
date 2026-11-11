import importlib.util
import sys
import time
import types
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import jwt
import pytest

from config import settings

MODULE_PATH = Path(__file__).resolve().parents[1] / "odoo_addons/miro_ai/controllers/ask_flow.py"
SECRET = "s" * 48
NOW = datetime(2026, 1, 1, 12, 0, 0)
JOB_ID = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def ask_flow(monkeypatch):
    odoo = types.ModuleType("odoo")
    odoo.fields = types.SimpleNamespace(Datetime=types.SimpleNamespace(now=lambda: NOW))
    osv = types.ModuleType("odoo.osv")
    expression = types.ModuleType("odoo.osv.expression")
    expression.OR = lambda domains: ["OR", *domains]
    odoo.osv = osv
    osv.expression = expression
    monkeypatch.setitem(sys.modules, "odoo", odoo)
    monkeypatch.setitem(sys.modules, "odoo.osv", osv)
    monkeypatch.setitem(sys.modules, "odoo.osv.expression", expression)
    spec = importlib.util.spec_from_file_location("miro_ask_flow_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _user(is_admin=False):
    return types.SimpleNamespace(
        id=7,
        login="alice",
        env=types.SimpleNamespace(cr=types.SimpleNamespace(dbname="prod_db")),
        has_group=lambda xmlid: is_admin and xmlid == "base.group_system",
    )


def _decode(headers, secret=SECRET):
    scheme, token = headers["Authorization"].split(" ")
    assert scheme == "Bearer"
    return jwt.decode(token, secret, algorithms=[settings.JWT_ALGORITHM], options={"require": ["exp"]})


def _env():
    env = MagicMock()
    env.__getitem__.return_value = MagicMock()
    return env, env["res.users.apikeys"]


def test_token_is_accepted_by_the_backend_verifier(ask_flow):
    token = ask_flow.generate_jwt_token({"sub": "7", "exp": int(time.time()) + 60}, SECRET)

    claims = jwt.decode(token, SECRET, algorithms=[settings.JWT_ALGORITHM], options={"require": ["exp"]})

    assert claims["sub"] == "7"


def test_token_signed_with_another_secret_is_rejected(ask_flow):
    token = ask_flow.generate_jwt_token({"sub": "7", "exp": int(time.time()) + 60}, SECRET)

    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, "x" * 48, algorithms=[settings.JWT_ALGORITHM])


def test_headers_carry_the_requester_identity(ask_flow):
    headers = ask_flow.backend_headers(SECRET, _user(), 3, [1, 2], "key-123")

    claims = _decode(headers)
    claims.pop("exp")
    assert headers["Content-Type"] == "application/json"
    assert claims == {
        "sub": "7", "uid": 7, "login": "alice", "company_id": 3,
        "db": "prod_db", "groups": [1, 2], "api_key": "key-123", "is_admin": False,
    }


def test_token_expires_within_five_minutes(ask_flow):
    before = int(time.time())

    expiry = _decode(ask_flow.backend_headers(SECRET, _user(), 3, []))["exp"]

    assert before < expiry <= int(time.time()) + 300


@pytest.mark.parametrize("is_admin", [True, False])
def test_admin_flag_follows_the_system_group(ask_flow, is_admin):
    headers = ask_flow.backend_headers(SECRET, _user(is_admin), 3, [])

    assert _decode(headers)["is_admin"] is is_admin


@pytest.mark.parametrize("job_id", [JOB_ID, "f" * 32])
def test_valid_job_ids_are_accepted(ask_flow, job_id):
    assert ask_flow.is_job_id(job_id)


@pytest.mark.parametrize(
    "job_id",
    [None, 123, "", JOB_ID[:-1], JOB_ID + "0", JOB_ID.upper(), JOB_ID + "\n", "../" + JOB_ID[3:], "g" * 32],
)
def test_malformed_job_ids_are_refused(ask_flow, job_id):
    assert not ask_flow.is_job_id(job_id)


def test_requester_scope_lists_company_and_group_ids(ask_flow):
    env = types.SimpleNamespace(
        company=types.SimpleNamespace(id=4),
        user=types.SimpleNamespace(groups_id=[types.SimpleNamespace(id=1), types.SimpleNamespace(id=9)]),
    )

    assert ask_flow.requester_scope(env) == (4, [1, 9])


def test_requester_key_is_committed_before_it_is_returned(ask_flow):
    env, apikeys = _env()
    apikeys._generate.return_value = "api-key"

    assert ask_flow.issue_requester_key(env, JOB_ID) == "api-key"
    apikeys._generate.assert_called_once_with(None, ask_flow.KEY_PREFIX + JOB_ID)
    env.cr.commit.assert_called_once_with()


def test_requester_key_failure_returns_none_without_commit(ask_flow):
    env, apikeys = _env()
    apikeys._generate.side_effect = RuntimeError("no key")

    assert ask_flow.issue_requester_key(env, JOB_ID) is None
    env.cr.commit.assert_not_called()


def test_revoking_a_job_also_removes_stale_keys(ask_flow):
    env, apikeys = _env()
    found = apikeys.sudo.return_value.search.return_value

    ask_flow.revoke_requester_keys(env, JOB_ID)

    domain = apikeys.sudo.return_value.search.call_args.args[0]
    assert domain[0] == "OR"
    assert domain[1] == [("name", "=", ask_flow.KEY_PREFIX + JOB_ID)]
    assert domain[2] == [
        ("name", "=like", f"{ask_flow.KEY_PREFIX}%"),
        ("create_date", "<", NOW - timedelta(seconds=ask_flow.STALE_KEY_SECONDS)),
    ]
    found._remove.assert_called_once_with()
    env.cr.commit.assert_called_once_with()


def test_revoking_without_a_job_only_removes_stale_keys(ask_flow):
    env, apikeys = _env()

    ask_flow.revoke_requester_keys(env)

    domain = apikeys.sudo.return_value.search.call_args.args[0]
    assert domain[0] == ("name", "=like", f"{ask_flow.KEY_PREFIX}%")


def test_revocation_failure_rolls_back_and_does_not_raise(ask_flow):
    env, apikeys = _env()
    apikeys.sudo.return_value.search.return_value._remove.side_effect = RuntimeError("db down")

    ask_flow.revoke_requester_keys(env, JOB_ID)

    env.cr.rollback.assert_called_once_with()
    env.cr.commit.assert_not_called()
