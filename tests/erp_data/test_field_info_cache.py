from unittest.mock import MagicMock

import pytest

from erp_data.tools import read_tools


@pytest.fixture
def connector(monkeypatch):
    read_tools._field_cache.clear()
    mock = MagicMock()
    mock.fields_get.side_effect = lambda uid, model, names: {names[0]: {"type": "char", "seen_by": uid}}
    monkeypatch.setattr(read_tools, "_get_connector", lambda: mock)
    yield mock
    read_tools._field_cache.clear()


def _as_user(monkeypatch, uid):
    monkeypatch.setattr(read_tools, "require_execution_uid", lambda: uid)


def test_a_field_description_is_not_shared_between_users(connector, monkeypatch):
    _as_user(monkeypatch, 7)
    assert read_tools._field_info("res.partner", "name")["seen_by"] == 7
    _as_user(monkeypatch, 8)
    assert read_tools._field_info("res.partner", "name")["seen_by"] == 8
    assert connector.fields_get.call_count == 2


def test_the_same_user_is_served_from_the_cache(connector, monkeypatch):
    _as_user(monkeypatch, 7)
    read_tools._field_info("res.partner", "name")
    read_tools._field_info("res.partner", "name")
    assert connector.fields_get.call_count == 1
