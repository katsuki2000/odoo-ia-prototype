from fastapi.testclient import TestClient

from api.main import app
from config.settings import CORS_ALLOWED_ORIGINS, parse_cors_origins


def test_no_origin_is_allowed_by_default():
    assert CORS_ALLOWED_ORIGINS == []


def test_parse_keeps_explicit_origins_only():
    raw = " https://erp.example.com/ , http://localhost:8069,,*"
    assert parse_cors_origins(raw) == ["https://erp.example.com", "http://localhost:8069"]


def test_parse_of_an_empty_value_allows_nothing():
    assert parse_cors_origins("") == []
    assert parse_cors_origins(" , ") == []


def test_preflight_from_a_foreign_origin_gets_no_cors_grant():
    response = TestClient(app).options(
        "/api/v1/ask",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-credentials" not in response.headers


def test_simple_request_from_a_foreign_origin_gets_no_cors_grant():
    response = TestClient(app).get("/health", headers={"Origin": "https://evil.example"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
