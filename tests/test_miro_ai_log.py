import importlib.util
import sys
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "odoo_addons/miro_ai/models/miro_ai_log.py"


@pytest.fixture
def log_module(monkeypatch):
    odoo = types.ModuleType("odoo")
    odoo.models = types.SimpleNamespace(Model=object)
    odoo.fields = MagicMock()
    odoo.api = types.SimpleNamespace(
        depends=lambda *args: lambda method: method,
        model=lambda method: method,
    )
    odoo_osv = types.ModuleType("odoo.osv")
    expression = types.ModuleType("odoo.osv.expression")
    expression.OR = lambda domains: domains
    monkeypatch.setitem(sys.modules, "odoo", odoo)
    monkeypatch.setitem(sys.modules, "odoo.osv", odoo_osv)
    monkeypatch.setitem(sys.modules, "odoo.osv.expression", expression)
    spec = importlib.util.spec_from_file_location("miro_ai_log_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("value", "expected_type", "default", "expected"),
    [
        ('[{"title": "source"}]', list, [], [{"title": "source"}]),
        ("not json", list, [], []),
        ('{"route": "system"}', list, [], []),
        ('"system"', dict, {}, {}),
        ("", dict, {}, {}),
    ],
)
def test_json_field_parsing_checks_shape_and_uses_default(
    log_module, value, expected_type, default, expected
):
    assert log_module._parse_json_field(value, "field", 1, expected_type, default) == expected


def test_sources_count_handles_malformed_and_empty_values(log_module):
    records = [
        types.SimpleNamespace(sources_text='[1, 2]', id=1),
        types.SimpleNamespace(sources_text="not json", id=2),
        types.SimpleNamespace(sources_text="", id=3),
    ]

    log_module.MiroAiLog._compute_sources_count(records)

    assert [record.sources_count for record in records] == [2, 0, 0]


def test_history_uses_empty_defaults_for_invalid_json_shapes(log_module):
    record = types.SimpleNamespace(
        metadata_text='["unexpected"]',
        sources_text='{"unexpected": true}',
        id=1,
        question="Question",
        answer="Answer",
        state="success",
        create_date=None,
    )
    model = types.SimpleNamespace(
        search=lambda domain, order: [record],
    )

    history = log_module.MiroAiLog.get_session_history(model, "session")

    assert history[0]["sources"] == []
    assert history[0]["route"] is None
    assert history[0]["confidence"] is None


def test_sessions_are_grouped_and_fetch_the_latest_preview(log_module):
    recent = datetime(2026, 10, 29, 10, 0)
    older = datetime(2026, 10, 28, 10, 0)
    groups = [
        {
            "session_id": "recent",
            "create_date": recent,
            "session_id_count": 4,
        },
        {
            "session_id": "older",
            "create_date": older,
            "session_id_count": 2,
        },
    ]
    latest_logs = [
        types.SimpleNamespace(session_id="older", question="Older question", create_date=older),
        types.SimpleNamespace(session_id="recent", question="Recent question", create_date=recent),
    ]
    model = types.SimpleNamespace(
        read_group=lambda domain, fields, groupby, **kwargs: groups,
        search=lambda domain, order: latest_logs,
    )

    sessions = log_module.MiroAiLog.get_sessions(model, limit=2)

    assert [session["session_id"] for session in sessions] == ["recent", "older"]
    assert [session["preview"] for session in sessions] == ["Recent question", "Older question"]
    assert [session["message_count"] for session in sessions] == [4, 2]


def test_sessions_reject_invalid_limits_and_cap_large_requests(log_module):
    calls = []
    model = types.SimpleNamespace(
        read_group=lambda domain, fields, groupby, **kwargs: calls.append(kwargs) or [],
    )

    with pytest.raises(ValueError):
        log_module.MiroAiLog.get_sessions(model, limit=0)

    log_module.MiroAiLog.get_sessions(model, limit=5000)
    assert calls[0]["limit"] == log_module.MAX_SESSION_LIST_LIMIT


def test_sessions_skip_incomplete_group_results(log_module):
    model = types.SimpleNamespace(
        read_group=lambda domain, fields, groupby, **kwargs: [
            {"session_id": False, "create_date": None},
        ],
    )

    assert log_module.MiroAiLog.get_sessions(model) == []
