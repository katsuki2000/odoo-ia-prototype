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

from config import settings

from api import auth
from api.main import app

SECRET = "s" * 40
ADMIN_ROUTES = [("get", "/api/v1/ingestion/status")]
AUTHENTICATED_ROUTES = [
    ("post", "/api/v1/ask/jobs"),
    ("get", "/api/v1/ask/jobs/nonexistent-id"),
]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "JWT_SECRET", SECRET)
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


def test_system_request_without_requester_api_key_is_rejected_before_graph(client):
    job_id = "c" * 32
    with patch("api.routes.ask.query_graph") as query_graph:
        accepted = client.post(
            "/api/v1/ask/jobs",
            headers=_headers(),
            json={
                "job_id": job_id,
                "question": "Combien de clients ?",
                "session_id": "s",
                "company_id": 1,
                "source_mode": "system",
            },
        )
        assert accepted.status_code == 202
        deadline = time.monotonic() + 5.0
        while True:
            body = client.get(f"/api/v1/ask/jobs/{job_id}", headers=_headers()).json()
            if body["status"] != "pending" or time.monotonic() > deadline:
                break
            time.sleep(0.01)
    assert (body["status"], body["error_status"]) == ("error", 403)
    query_graph.assert_not_called()


def test_ingestion_status_reachable_with_an_admin_token(client):
    with patch("api.routes.ingestion.ChromaManager") as manager:
        manager.return_value.get_stats.return_value = {"total_chunks": 0}
        response = client.get("/api/v1/ingestion/status", headers=_headers(is_admin=True))
    assert response.status_code == 200


def test_require_admin_accepts_only_a_true_admin_claim():
    assert auth.require_admin({"uid": 1, "is_admin": True})["uid"] == 1
    for claims in ({"uid": 1}, {"uid": 1, "is_admin": False}, {"uid": 1, "is_admin": 1}):
        with pytest.raises(HTTPException) as excinfo:
            auth.require_admin(claims)
        assert excinfo.value.status_code == 403


def test_api_listens_on_loopback_by_default():
    root = Path(__file__).resolve().parents[2]
    env = {key: value for key, value in os.environ.items() if key != "API_HOST"}
    output = subprocess.run(
        [sys.executable, "-c", "import config.settings as s; print(s.API_HOST)"],
        cwd=root, env=env, capture_output=True, text=True, check=True,
    ).stdout.strip().splitlines()[-1]
    assert output == "127.0.0.1"
