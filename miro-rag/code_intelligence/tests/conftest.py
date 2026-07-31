"""
code_intelligence/tests/conftest.py

Shared pytest fixtures for code_intelligence/tests/.

live_client is needed by both J5 (test_j5_live_validation.py) and J6
(test_j6_context_validation.py). Defining it here at conftest level makes it
available to every test file in code_intelligence/tests/ that needs a live
Odoo connection, without duplicating the skip/setup logic per file.
"""

from __future__ import annotations

import os
import pytest

from code_intelligence.odoo_rpc_client import OdooRpcClient

TEST_PASSWORD = os.getenv("ODOO_J5_TEST_PASSWORD", "J5TestPassword2026!")
TEST_USERS = ("test_both_2026", "test_regional_2026", "test_no_group_2026")


@pytest.fixture(scope="module")
def live_client() -> OdooRpcClient:
    client = OdooRpcClient()
    try:
        admin_uid = client.authenticate_admin()
    except Exception as exc:
        pytest.skip(f"Live Odoo admin authentication is not available: {exc}")

    missing_modules = [
        module
        for module in ("custom_credit_note_approval", "custom_credit_note_visibility_rules")
        if not client.execute_kw(
            admin_uid,
            "ir.module.module",
            "search",
            [[("name", "=", module), ("state", "=", "installed")]],
            {"limit": 1},
        )
    ]
    if missing_modules:
        pytest.skip(f"Required Odoo modules are not installed: {missing_modules}")

    for login in TEST_USERS:
        client.set_user_password(admin_uid, login, TEST_PASSWORD)

    if not client.execute_kw(
        admin_uid,
        "account.move",
        "search",
        [[("move_type", "=", "out_refund"), ("amount_total", ">=", 80000)]],
        {"limit": 1},
    ):
        pytest.skip("No live 80k customer credit note found for live validation.")

    return client
