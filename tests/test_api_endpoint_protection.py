import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api import auth
from api.main import app

SECRET = "s" * 40
ADMIN_ROUTES = [
    ("post", "/api/v1/reindex"),
    ("get", "/api/v1/ingestion/status"),
    ("post", "/api/v1/ingestion/scheduled-scan"),
]
AUTHENTICATED_ROUTES = [
    ("post", "/api/v1/ask"),
    ("get", "/api/v1/ask/jobs/nonexistent-id"),
]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    return TestClient(app)


def _headers(**claims):
    payload = {"uid": 7, "exp": int(time.time()) + 60, **claims}
    return {"Authorization": f"Bearer {jwt.encode(payload, SECRET, algorithm='HS256')}"}


@pytest.mark.parametrize("method,path", ADMIN_ROUTES + AUTHENTICATED_ROUTES)
def test_routes_refuse_calls_without_a_token(client, method, path):
    response = getattr(client, method)(path)
    assert response.status_code in (401, 403)


@pytest.mark.parametrize("method,path", ADMIN_ROUTES)
@pytest.mark.parametrize("claims", [{}, {"is_admin": False}, {"is_admin": "true"}])
def test_admin_routes_refuse_non_admin_tokens(client, method, path, claims):
    response = getattr(client, method)(path, headers=_headers(**claims))
    assert response.status_code == 403


@pytest.mark.parametrize("method,path", AUTHENTICATED_ROUTES)
@pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning")
def test_authenticated_routes_refuse_a_forged_token(client, method, path):
    forged = jwt.encode({"uid": 1, "exp": int(time.time()) + 60}, "default_insecure_secret_for_dev", algorithm="HS256")
    response = getattr(client, method)(path, headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


def test_health_stays_public(client):
    assert client.get("/health").status_code == 200


def test_scheduled_scan_reachable_with_an_admin_token(client):
    with patch("api.routes_ingestion.run_scheduled_scan") as scan:
        scan.return_value = {"status": "success", "files_scanned": 0, "chunks_added": 0, "duration_ms": 0}
        response = client.post("/api/v1/ingestion/scheduled-scan", headers=_headers(is_admin=True))
    assert response.status_code != 403
    assert response.status_code != 401


def test_require_admin_accepts_only_a_true_admin_claim():
    assert auth.require_admin({"uid": 1, "is_admin": True})["uid"] == 1
    for claims in ({"uid": 1}, {"uid": 1, "is_admin": False}, {"uid": 1, "is_admin": 1}):
        with pytest.raises(HTTPException) as excinfo:
            auth.require_admin(claims)
        assert excinfo.value.status_code == 403


def test_api_listens_on_loopback_by_default():
    root = Path(__file__).resolve().parents[1]
    env = {key: value for key, value in os.environ.items() if key != "API_HOST"}
    output = subprocess.run(
        [sys.executable, "-c", "import config.settings as s; print(s.API_HOST)"],
        cwd=root, env=env, capture_output=True, text=True, check=True,
    ).stdout.strip().splitlines()[-1]
    assert output == "127.0.0.1"
