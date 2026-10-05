"""Hermetic tests for the case worker."""

import json
from types import SimpleNamespace

from core.evaluation import case_worker as cw

CASES = [
    {"case_id": "a", "question": "q1", "user_context": {"user": "base.user_demo", "language": "en_US"}},
    {"case_id": "b", "question": "q2", "user_context": {"user": "base.user_demo", "language": "en_US"}},
]
CREDENTIALS = {"base.user_demo": {"uid": 6, "api_key": "k", "groups": [1, 2]}}


def fake_ask(calls):
    def ask(**kwargs):
        calls.append(kwargs)
        if kwargs["question"] == "q2":
            raise ConnectionError("down")
        return SimpleNamespace(model_dump=lambda mode: {"answer": "ok", "mode": mode})
    return ask


def test_run_cases_writes_raw_rows_and_captures_errors(tmp_path):
    calls = []
    output = tmp_path / "raw" / "x.jsonl"
    assert cw.run_cases(CASES, CREDENTIALS, output, fake_ask(calls)) == 2
    rows = cw.read_raw(output)
    assert rows["a"]["raw"]["answer"] == "ok"
    assert rows["b"]["raw"]["error"].startswith("ConnectionError")
    assert calls[0]["uid"] == 6 and calls[0]["user_groups"] == [1, 2] and calls[0]["language"] == "en_US"


def test_run_cases_resumes_without_repeating_done_cases(tmp_path):
    output = tmp_path / "x.jsonl"
    output.write_text(json.dumps({"case_id": "a", "raw": {"answer": "old"}}) + "\n", encoding="utf-8")
    calls = []
    assert cw.run_cases(CASES, CREDENTIALS, output, fake_ask(calls)) == 1
    assert [call["question"] for call in calls] == ["q2"]
    assert cw.read_raw(output)["a"]["raw"]["answer"] == "old"


def test_read_raw_of_missing_file_is_empty(tmp_path):
    assert cw.read_raw(tmp_path / "absent.jsonl") == {}
