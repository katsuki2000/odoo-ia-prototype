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

from code_intelligence.agent.rpc_client import OdooRpcClient
from code_intelligence.tests._live_odoo import skip_unless_modules_installed

TEST_PASSWORD = os.getenv("ODOO_J5_TEST_PASSWORD", "J5TestPassword2026!")
TEST_USERS = ("test_both_2026", "test_regional_2026", "test_no_group_2026")


@pytest.fixture(scope="module")
def live_client() -> OdooRpcClient:
    client = OdooRpcClient()
    try:
        admin_uid = client.authenticate_admin()
    except Exception as exc:
        pytest.skip(f"Live Odoo admin authentication is not available: {exc}")

    skip_unless_modules_installed(
        client, admin_uid, ("miro_credit_note_approval", "miro_credit_note_visibility_rules"),
    )

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


@pytest.fixture(scope="module")
def alpha_company_id(live_client: OdooRpcClient) -> int:
    """Resout 'Company Alpha' par NOM plutot que par id code en dur -- les ids
    ne sont pas stables entre les deux machines du projet (todo/rules.md,
    interoperabilite). Todo/contexte.txt section 321/322 : un id code en dur
    (=1) a casse des tests J6 des que 'My Company' (qui etait id=1) a ete
    archivee et que Company Alpha (id=2 sur cette instance, mais pas
    garanti ailleurs) est devenue l'unique societe active.
    """
    admin_uid = live_client.authenticate_admin()
    ids = live_client.execute_kw(
        admin_uid, "res.company", "search", [[("name", "=", "Company Alpha")]], {"limit": 1},
    )
    if not ids:
        pytest.skip("Company 'Company Alpha' not found -- run tools/full_setup.py first.")
    return int(ids[0])


@pytest.fixture(scope="module")
def invalid_company_id(live_client: OdooRpcClient) -> int:
    """Id garanti ne correspondre a AUCUN res.company reel, calcule
    dynamiquement (max des ids existants + marge) plutot que code en dur --
    utilise pour declencher le rejet Odoo 'unauthorized/invalid company'
    sans dependre d'une societe archivee ou etrangere specifique.
    """
    admin_uid = live_client.authenticate_admin()
    ids = live_client.execute_kw(
        admin_uid, "res.company", "search", [[]], {"context": {"active_test": False}},
    )
    return (max(ids) if ids else 0) + 1000
