import time

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from api import auth

STRONG_SECRET = "s" * 40
LEGACY_SECRET = "default_insecure_secret_for_dev"


def _credentials(token):
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _token(secret, **claims):
    payload = {"uid": 7, **claims}
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture
def strong_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", STRONG_SECRET)


def test_missing_secret_is_refused(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        auth.get_jwt_secret()


@pytest.mark.parametrize("secret", ["", "a" * 31, LEGACY_SECRET])
def test_weak_secret_is_refused(monkeypatch, secret):
    monkeypatch.setenv("JWT_SECRET", secret)
    with pytest.raises(RuntimeError):
        auth.get_jwt_secret()


def test_strong_secret_is_returned(strong_secret):
    assert auth.get_jwt_secret() == STRONG_SECRET


def test_valid_token_is_accepted(strong_secret):
    token = _token(STRONG_SECRET, exp=int(time.time()) + 60)
    assert auth.verify_token(_credentials(token))["uid"] == 7


def test_token_without_expiration_is_rejected(strong_secret):
    with pytest.raises(HTTPException) as excinfo:
        auth.verify_token(_credentials(_token(STRONG_SECRET)))
    assert excinfo.value.status_code == 401


def test_expired_token_is_rejected(strong_secret):
    token = _token(STRONG_SECRET, exp=int(time.time()) - 60)
    with pytest.raises(HTTPException) as excinfo:
        auth.verify_token(_credentials(token))
    assert excinfo.value.status_code == 401
    assert "expired" in excinfo.value.detail


def test_token_signed_with_the_legacy_default_secret_is_rejected(strong_secret):
    token = _token(LEGACY_SECRET, exp=int(time.time()) + 60)
    with pytest.raises(HTTPException) as excinfo:
        auth.verify_token(_credentials(token))
    assert excinfo.value.status_code == 401
