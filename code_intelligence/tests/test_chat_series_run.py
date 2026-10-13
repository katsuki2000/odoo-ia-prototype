import json as json_module

import jwt
import pytest
import requests

from code_intelligence.evaluation.chat_series import run as chat_run
from code_intelligence.evaluation.chat_series.run import (
    RunSettings,
    build_request,
    classify_outcome,
    ensure_runnable,
    load_previous_report,
    run_series,
)


class FakeResponse:
    def __init__(self, status_code=200, body=None, text=""):
        self.status_code = status_code
        self._body = body
        self.text = text

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def _answer(question="q"):
    return {"answer": "reponse", "question": question, "route": "code_intelligence", "evidence_status": "sufficient"}


def _series(status="frozen", count=3):
    cases = [
        {"case_id": f"c{index}", "series": 1, "anchor": index == 1, "question": f"question {index}", "language": "fr_FR"}
        for index in range(1, count + 1)
    ]
    return {"series": 1, "status": status, "cases": cases}


class ScriptedPost:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.payloads = []

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.payloads.append(json)
        outcome = self.outcomes.pop(0) if self.outcomes else FakeResponse(200, _answer())
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


SETTINGS = RunSettings(base_url="http://api.test")


def _run(post, tmp_path, *, series=None, settings=SETTINGS, previous=None, only=None):
    return run_series(
        series or _series(), "digest-1", settings=settings, post=post, headers={},
        output_path=tmp_path / "report.json", previous=previous, only=only,
    )


def test_request_carries_source_mode_and_case_language():
    case = _series()["cases"][0]

    default = build_request(case, SETTINGS, "s1")
    forced = build_request(case, RunSettings(base_url="x", source_mode="systeme", language_mode="case"), "s1")

    assert "source_mode" not in default and "language" not in default
    assert forced["source_mode"] == "systeme"
    assert forced["language"] == "fr-FR"
    assert forced["question"] == "question 1"


def test_clean_answer_is_recorded_with_response_and_latency(tmp_path):
    report = _run(ScriptedPost(), tmp_path)

    record = report["results"]["c1"]
    assert record["transport_status"] == "ok"
    assert record["response"]["route"] == "code_intelligence"
    assert record["anchor"] is True
    assert record["latency_s"] >= 0
    assert report["status"] == "complete"
    assert report["invalidated_attempts"] == []


def test_service_unavailable_is_recorded_apart_not_as_an_answer(tmp_path):
    post = ScriptedPost(FakeResponse(503, text="Service Unavailable: Upstream provider down."))

    report = _run(post, tmp_path)

    assert "c1" not in report["results"]
    assert report["invalidated_attempts"][0]["transport_status"] == "transport_error"
    assert report["invalidated_attempts"][0]["http_status"] == 503
    assert report["status"] == "incomplete"


def test_timeout_is_a_transport_error(tmp_path):
    report = _run(ScriptedPost(requests.Timeout("read timed out")), tmp_path)

    attempt = report["invalidated_attempts"][0]
    assert attempt["transport_status"] == "transport_error"
    assert "Timeout" in attempt["error"]
    assert attempt["http_status"] is None


def test_internal_error_is_not_counted_as_a_transport_failure(tmp_path):
    report = _run(ScriptedPost(FakeResponse(500, text="RAG Graph error: boom")), tmp_path)

    assert report["invalidated_attempts"][0]["transport_status"] == "server_error"


def test_report_is_saved_after_each_question(tmp_path):
    seen = []

    def post(url, json=None, headers=None, timeout=None):
        report_file = tmp_path / "report.json"
        seen.append(len(json_module.loads(report_file.read_text())["results"]) if report_file.exists() else 0)
        return FakeResponse(200, _answer())

    _run(post, tmp_path)

    assert seen == [0, 1, 2]


def test_resume_asks_only_the_questions_without_a_clean_answer(tmp_path):
    first = ScriptedPost(FakeResponse(200, _answer()), FakeResponse(503, text="down"), FakeResponse(200, _answer()))
    _run(first, tmp_path)
    second = ScriptedPost()

    report = _run(second, tmp_path, previous=load_previous_report(tmp_path / "report.json"))

    assert [payload["question"] for payload in second.payloads] == ["question 2"]
    assert set(report["results"]) == {"c1", "c2", "c3"}
    assert len(report["invalidated_attempts"]) == 1
    assert report["status"] == "complete"


def test_resume_refuses_a_changed_series_or_settings(tmp_path):
    _run(ScriptedPost(), tmp_path)
    previous = load_previous_report(tmp_path / "report.json")

    with pytest.raises(ValueError, match="series file changed"):
        run_series(_series(), "digest-2", settings=SETTINGS, post=ScriptedPost(), headers={}, previous=previous)
    with pytest.raises(ValueError, match="source_mode"):
        run_series(
            _series(), "digest-1", settings=RunSettings(base_url="x", source_mode="systeme"),
            post=ScriptedPost(), headers={}, previous=previous,
        )


def test_client_error_stops_the_series(tmp_path):
    post = ScriptedPost(FakeResponse(401, text="Invalid token"))

    report = _run(post, tmp_path)

    assert len(post.payloads) == 1
    assert report["aborted_reason"].startswith("client_error HTTP 401")


def test_consecutive_failures_stop_the_series(tmp_path):
    post = ScriptedPost(*[FakeResponse(503, text="down")] * 3)

    report = _run(post, tmp_path, series=_series(count=5), settings=RunSettings(base_url="x", max_consecutive_failures=2))

    assert len(post.payloads) == 2
    assert "2 consecutive" in report["aborted_reason"]


def test_a_clean_answer_resets_the_failure_count(tmp_path):
    post = ScriptedPost(FakeResponse(503, text="down"), FakeResponse(200, _answer()), FakeResponse(503, text="down"))

    report = _run(post, tmp_path, settings=RunSettings(base_url="x", max_consecutive_failures=2))

    assert len(post.payloads) == 3
    assert report["aborted_reason"] is None


def test_local_token_carries_groups_only_when_given(monkeypatch):
    secret = "s" * 32
    monkeypatch.setenv("JWT_SECRET", secret)
    monkeypatch.delenv(chat_run.TOKEN_ENV, raising=False)

    def claims(settings):
        token = chat_run.build_headers(settings)["Authorization"].split(" ", 1)[1]
        return jwt.decode(token, secret, algorithms=["HS256"])

    assert "groups" not in claims(SETTINGS)
    with_groups = claims(RunSettings(base_url="x", groups=("base.group_user", "hr.group_hr_user")))
    assert with_groups["groups"] == ["base.group_user", "hr.group_hr_user"]
    assert with_groups["uid"] == 2


def test_groups_must_be_xml_ids():
    with pytest.raises(ValueError, match="xml_ids"):
        RunSettings(base_url="x", groups=("12",))


def test_groups_are_refused_with_a_real_token(monkeypatch):
    monkeypatch.setenv(chat_run.TOKEN_ENV, "real-token")

    with pytest.raises(ValueError, match="real token"):
        chat_run.build_headers(RunSettings(base_url="x", groups=("base.group_user",)))
    assert chat_run.build_headers(SETTINGS)["Authorization"] == "Bearer real-token"


def test_resume_checks_groups_and_accepts_reports_without_the_key(tmp_path):
    grouped = RunSettings(base_url="x", groups=("base.group_user",))
    _run(ScriptedPost(), tmp_path, settings=grouped)
    previous = load_previous_report(tmp_path / "report.json")

    _run(ScriptedPost(), tmp_path, settings=grouped, previous=previous)
    with pytest.raises(ValueError, match="groups"):
        _run(ScriptedPost(), tmp_path, settings=SETTINGS, previous=previous)

    legacy = {"series_digest": "digest-1", "settings": {"user_uid": 2, "company_id": 1, "source_mode": None, "language_mode": "none"}}
    chat_run.check_resumable(legacy, "digest-1", SETTINGS)


def test_each_question_gets_its_own_session(tmp_path):
    post = ScriptedPost()

    _run(post, tmp_path)

    sessions = [payload["session_id"] for payload in post.payloads]
    assert len(set(sessions)) == 3


def test_only_selects_cases_and_rejects_unknown_ids(tmp_path):
    post = ScriptedPost()

    report = _run(post, tmp_path, only=["c2"])

    assert [payload["question"] for payload in post.payloads] == ["question 2"]
    assert report["status"] == "incomplete"
    with pytest.raises(ValueError, match="unknown case ids"):
        _run(ScriptedPost(), tmp_path, only=["nope"])


def test_draft_series_is_refused_unless_allowed():
    with pytest.raises(ValueError, match="frozen"):
        ensure_runnable(_series(status="draft_pending_pmm_review"), allow_draft=False)

    ensure_runnable(_series(status="draft_pending_pmm_review"), allow_draft=True)
    ensure_runnable(_series(status="frozen"), allow_draft=False)


def test_outcome_classification():
    assert classify_outcome(200, {"answer": "x"}) == "ok"
    assert classify_outcome(200, None) == "server_error"
    assert classify_outcome(503, None) == "transport_error"
    assert classify_outcome(None, None) == "transport_error"
    assert classify_outcome(401, None) == "client_error"
    assert classify_outcome(500, None) == "server_error"


def test_report_is_valid_json_on_disk(tmp_path):
    _run(ScriptedPost(), tmp_path)

    data = json_module.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    assert data["series"] == 1 and data["series_digest"] == "digest-1"
    assert chat_run.FROZEN_STATUS == "frozen"
