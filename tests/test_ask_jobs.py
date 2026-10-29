import threading
import time

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api import routes_ask
from api.ask_jobs import AskJobStore, DuplicateJobError, JobCapacityError
from api.auth import get_current_user
from api.schemas import AskResponseV1
from core.schemas import AssistantResponse

JOB_ID = "a" * 32
OTHER_JOB_ID = "b" * 32


def _graph_answer(text):
    return AssistantResponse(answer=text, confidence=1.0)


def _answer(text="done"):
    return AskResponseV1(answer=text, question="q", session_id="s")


def _wait_until_finished(poll, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = poll()
        if job is not None and job.status != "pending":
            return job
        time.sleep(0.01)
    raise AssertionError("job still pending")


@pytest.fixture
def store():
    return AskJobStore(workers=2, max_pending=2, ttl_seconds=60)


def test_job_is_pending_until_the_work_returns_then_done(store):
    release = threading.Event()
    store.submit(JOB_ID, 7, "question", lambda: release.wait(5) and _answer("hello"))
    assert store.get(JOB_ID, 7).status == "pending"
    release.set()
    job = _wait_until_finished(lambda: store.get(JOB_ID, 7))
    assert (job.status, job.result.answer, job.error_status) == ("done", "hello", None)
    assert job.elapsed_ms >= 0


def test_job_owned_by_someone_else_or_unknown_is_not_returned(store):
    store.submit(JOB_ID, 7, "question", _answer)
    assert store.get(JOB_ID, 8) is None
    assert store.get(OTHER_JOB_ID, 7) is None


def test_http_error_of_the_work_is_kept_on_the_job(store):
    def failing():
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    store.submit(JOB_ID, 7, "question", failing)
    job = _wait_until_finished(lambda: store.get(JOB_ID, 7))
    assert (job.status, job.error_status, job.error_detail, job.result) == (
        "error", 503, "Service temporarily unavailable.", None)


def test_unexpected_error_is_reported_without_its_details(store):
    def failing():
        raise ValueError("private detail")

    store.submit(JOB_ID, 7, "question", failing)
    job = _wait_until_finished(lambda: store.get(JOB_ID, 7))
    assert (job.error_status, job.error_detail) == (500, "Internal server error.")


def test_same_job_id_cannot_be_submitted_twice(store):
    store.submit(JOB_ID, 7, "question", _answer)
    with pytest.raises(DuplicateJobError):
        store.submit(JOB_ID, 7, "question", _answer)


def test_capacity_counts_only_pending_jobs(store):
    release = threading.Event()
    blocked = lambda: release.wait(5) and _answer()
    store.submit("1" * 32, 7, "question", blocked)
    store.submit("2" * 32, 7, "question", blocked)
    with pytest.raises(JobCapacityError):
        store.submit("3" * 32, 7, "question", _answer)
    release.set()
    _wait_until_finished(lambda: store.get("1" * 32, 7))
    _wait_until_finished(lambda: store.get("2" * 32, 7))
    store.submit("3" * 32, 7, "question", _answer)


def test_expired_job_is_dropped():
    expiring = AskJobStore(workers=1, max_pending=2, ttl_seconds=0)
    expiring.submit(JOB_ID, 7, "question", _answer)
    time.sleep(0.01)
    assert expiring.get(JOB_ID, 7) is None


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(routes_ask, "ask_jobs", AskJobStore(workers=1, max_pending=1, ttl_seconds=60))
    monkeypatch.setattr(routes_ask, "query_graph", lambda **kwargs: _graph_answer("hello"))
    app = FastAPI()
    app.include_router(routes_ask.router)
    app.dependency_overrides[get_current_user] = lambda: {"uid": 7, "api_key": "key", "groups": [], "company_id": 1}
    return TestClient(app)


def _payload(job_id=JOB_ID):
    return {"job_id": job_id, "question": "how?", "session_id": "s1", "company_id": 1}


def _poll_until_finished(client, job_id=JOB_ID):
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/ask/jobs/{job_id}").json()
        if body["status"] != "pending":
            return body
        time.sleep(0.01)
    raise AssertionError("job still pending")


def test_submitted_question_is_answered_through_polling(client):
    response = client.post("/api/v1/ask/jobs", json=_payload())
    assert (response.status_code, response.json()) == (202, {"job_id": JOB_ID})
    body = _poll_until_finished(client)
    assert (body["status"], body["result"]["answer"], body["question"]) == ("done", "hello", "how?")


def test_job_of_another_user_looks_unknown(client):
    client.post("/api/v1/ask/jobs", json=_payload())
    client.app.dependency_overrides[get_current_user] = lambda: {"uid": 8}
    assert client.get(f"/api/v1/ask/jobs/{JOB_ID}").status_code == 404


def test_duplicate_job_id_is_refused(client):
    client.post("/api/v1/ask/jobs", json=_payload())
    _poll_until_finished(client)
    assert client.post("/api/v1/ask/jobs", json=_payload()).status_code == 409


def test_job_id_must_be_a_32_character_hex_string(client):
    assert client.post("/api/v1/ask/jobs", json=_payload("not-a-job-id")).status_code == 422


def test_full_queue_answers_429(client, monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(routes_ask, "query_graph", lambda **kwargs: release.wait(5) and _graph_answer("x"))
    assert client.post("/api/v1/ask/jobs", json=_payload()).status_code == 202
    assert client.post("/api/v1/ask/jobs", json=_payload(OTHER_JOB_ID)).status_code == 429
    release.set()


def test_backend_failure_is_reported_as_a_public_error(client, monkeypatch):
    def failing(**kwargs):
        raise ConnectionError("inference server down")

    monkeypatch.setattr(routes_ask, "query_graph", failing)
    client.post("/api/v1/ask/jobs", json=_payload())
    body = _poll_until_finished(client)
    assert (body["status"], body["error_status"], body["error_detail"]) == (
        "error", 503, "Service temporarily unavailable.")


def test_synchronous_route_still_answers(client):
    response = client.post("/api/v1/ask", json={k: v for k, v in _payload().items() if k != "job_id"})
    assert (response.status_code, response.json()["answer"]) == (200, "hello")
