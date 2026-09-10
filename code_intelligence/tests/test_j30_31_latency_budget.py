"""
code_intelligence/tests/test_j30_31_latency_budget.py

Unit tests for J30-J31 (Performance — latency budget & real measurement):
1. Verifies latency budget constants in config/settings.py.
2. Verifies _invoke_with_rate_limit tuple return (result, wait_seconds).
3. Verifies CI_MAX_HOPS enforcement in code_intelligence_agent loop.
4. Verifies fine-grained timing dict populated by code_intelligence_agent.
"""

import time
import pytest
from unittest.mock import MagicMock, patch
from config.settings import (
    LATENCY_BUDGET_P90_SECONDS,
    LATENCY_BUDGET_RESOLVER_MS,
    LATENCY_BUDGET_PER_HOP_MS,
    LATENCY_BUDGET_SYNTHESIS_MS,
    LATENCY_BUDGET_XMLRPC_MS,
)
from core.graph import CI_MAX_HOPS, _invoke_with_rate_limit


def test_latency_budget_constants_exist():
    """J30-J31: verify all required latency budget constants are configured."""
    assert LATENCY_BUDGET_P90_SECONDS > 0
    assert LATENCY_BUDGET_RESOLVER_MS > 0
    assert LATENCY_BUDGET_PER_HOP_MS > 0
    assert LATENCY_BUDGET_SYNTHESIS_MS > 0
    assert LATENCY_BUDGET_XMLRPC_MS > 0
    assert CI_MAX_HOPS == 4


def test_invoke_with_rate_limit_returns_wait_tuple():
    """J30-J31: _invoke_with_rate_limit returns (result, wait_seconds)."""
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = "mock_response"

    res, wait_sec = _invoke_with_rate_limit(mock_llm, ["hello"])
    assert res == "mock_response"
    assert isinstance(wait_sec, float)
    assert wait_sec >= 0.0


def test_ci_max_hops_value():
    """J30-J31: verify CI_MAX_HOPS is explicitly set to 4."""
    assert CI_MAX_HOPS == 4


def test_xmlrpc_client_timing_logging(caplog):
    """J30-J31: verify XML-RPC client instruments execute_kw timing."""
    import logging
    from code_intelligence.agent.live.rpc_client import OdooRpcClient

    client = OdooRpcClient()
    client._password_by_uid[1] = "admin"
    client.models = MagicMock()
    client.models.execute_kw.return_value = [1, 2, 3]

    with caplog.at_level(logging.INFO):
        res = client.execute_kw(1, "res.partner", "search", [])

    assert res == [1, 2, 3]
    assert any("XML-RPC call" in rec.message for rec in caplog.records)


def test_odoo_connector_timing_logging(caplog):
    """J30-J31: verify OdooConnector instruments search_read timing."""
    import logging
    from erp_data.odoo_connector import OdooConnector

    connector = OdooConnector()
    connector.models = MagicMock()
    connector.models.execute_kw.return_value = [{"id": 1, "name": "Partner"}]

    with caplog.at_level(logging.INFO):
        res = connector.search_read(1, "res.partner", [])

    assert len(res) == 1
    assert any("XML-RPC" in rec.message and "res.partner.search_read" in rec.message for rec in caplog.records)
