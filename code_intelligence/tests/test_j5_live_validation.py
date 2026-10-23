"""
J5 live validation for Odoo ACL + ir.rule semantics.

These tests intentionally call a real Odoo 17 instance through XML-RPC. They
are skipped only when the live instance or required adversarial fixtures are
not reachable. The assertions encode the J5 divergences observed in :
ACL denial happens before record-rule evaluation, and Odoo combines applicable
group ir.rules with OR.
"""

from __future__ import annotations

import os
import xmlrpc.client
from pathlib import Path

import networkx as nx
import pytest

from code_intelligence.graph.nodes import ParsedModule
from code_intelligence.graph.symbols import build_module_symbol_registry
from code_intelligence.extractor.csv import parse_access_control_csv
from code_intelligence.graph.builder import OdooGraphBuilder
from code_intelligence.agent.live_validation import validate_live_rule_prediction
from code_intelligence.agent.rpc_client import OdooRpcClient
from code_intelligence.extractor.xml import parse_groups_from_xml, parse_ir_rules_from_xml
from config.settings import CUSTOM_ADDONS_PATH


pytestmark = pytest.mark.integration


TEST_PASSWORD = os.getenv("ODOO_J5_TEST_PASSWORD", "J5TestPassword2026!")
TEST_USERS = ("test_both_2026", "test_regional_2026", "test_no_group_2026")
ACCOUNT_MOVE_80K_REFUND_DOMAIN = [
    ("move_type", "=", "out_refund"),
    ("amount_total", ">=", 80000),
]


@pytest.fixture(scope="module")

def real_security_graph() -> nx.DiGraph:
    addons_root = Path(CUSTOM_ADDONS_PATH)
    module_names = ("miro_credit_note_approval", "miro_credit_note_visibility_rules")
    modules = {}

    for module_name in module_names:
        module_dir = addons_root / module_name
        if not module_dir.exists():
            pytest.skip(f"Required real Odoo module is missing: {module_dir}")

        parsed = ParsedModule(manifest=None)
        for xml_file in module_dir.rglob("*.xml"):
            parsed.groups.extend(parse_groups_from_xml(xml_file))
            parsed.rules.extend(parse_ir_rules_from_xml(xml_file))
        for csv_file in module_dir.rglob("*.csv"):
            parsed.acl_entries.extend(parse_access_control_csv(csv_file))
        modules[module_name] = parsed

    registry = build_module_symbol_registry(modules)
    return OdooGraphBuilder(registry, modules).build_graph()


def _authenticate(client: OdooRpcClient, login: str) -> int:
    return client.authenticate_user(login, TEST_PASSWORD)


def test_regional_user_has_live_billing_group_and_write_acl(live_client: OdooRpcClient):
    admin_uid = live_client.authenticate_admin()
    users = live_client.execute_kw(
        admin_uid,
        "res.users",
        "search_read",
        [[("login", "=", "test_regional_2026")]],
        {"fields": ["id", "login", "groups_id"], "limit": 1},
    )
    assert users

    groups = live_client.execute_kw(
        admin_uid,
        "res.groups",
        "read",
        [users[0]["groups_id"]],
        {"fields": ["name"]},
    )
    # Compare par NOM plutot que par id res.groups code en dur -- les ids de
    # res.groups dependent de l'ordre d'installation des modules, jamais
    # stables entre les deux machines du projet (todo/rules.md,
    # interoperabilite ; meme famille de fix que alpha_company_id/
    # invalid_company_id dans conftest.py, todo/contexte.txt section 321/322).
    group_names = {group["name"] for group in groups}
    assert "Billing" in group_names
    assert "Avoirs - Visibilite Regionale" in group_names

    uid = _authenticate(live_client, "test_regional_2026")
    assert live_client.check_access_rights(uid, "account.move", "read") is True
    assert live_client.check_access_rights(uid, "account.move", "write") is True


@pytest.mark.parametrize("operation", ["read", "write"])
def test_no_group_user_blocked_by_acl(live_client: OdooRpcClient, operation: str):
    uid = _authenticate(live_client, "test_no_group_2026")

    with pytest.raises(xmlrpc.client.Fault) as excinfo:
        live_client.search_as_user(
            uid,
            "account.move",
            ACCOUNT_MOVE_80K_REFUND_DOMAIN,
            operation=operation,
            limit=1,
        )

    fault = excinfo.value.faultString
    assert (
        "Access Denied by ACLs" in fault
        or "not allowed to access" in fault
        or "not allowed to modify" in fault
    )
    assert "account.move" in fault or "Journal Entry" in fault


@pytest.mark.parametrize("operation", ["read", "write"])
def test_regional_user_override_by_billing_group(live_client: OdooRpcClient, operation: str):
    uid = _authenticate(live_client, "test_regional_2026")

    record_ids = live_client.search_as_user(
        uid,
        "account.move",
        ACCOUNT_MOVE_80K_REFUND_DOMAIN,
        operation=operation,
        limit=5,
    )

    assert record_ids, (
        "Odoo live search must return the 80k credit note: the account.group_account_invoice "
        "Billing rule is OR-combined with the regional 50k rule, so the regional cap alone "
        "does not block this user."
    )


@pytest.mark.parametrize("operation", ["read", "write"])
def test_both_groups_user_access(live_client: OdooRpcClient, operation: str):
    uid = _authenticate(live_client, "test_both_2026")

    record_ids = live_client.search_as_user(
        uid,
        "account.move",
        ACCOUNT_MOVE_80K_REFUND_DOMAIN,
        operation=operation,
        limit=5,
    )

    assert record_ids


@pytest.mark.parametrize(
    ("login", "operation", "expected_allowed"),
    [
        ("test_no_group_2026", "read", False),
        ("test_no_group_2026", "write", False),
        ("test_regional_2026", "read", True),
        ("test_regional_2026", "write", True),
        ("test_both_2026", "read", True),
        ("test_both_2026", "write", True),
    ],
)
def test_live_rule_validator_matches_odoo_truth(
    live_client: OdooRpcClient,
    real_security_graph: nx.DiGraph,
    login: str,
    operation: str,
    expected_allowed: bool,
):
    result = validate_live_rule_prediction(
        live_client,
        real_security_graph,
        user_login=login,
        password=TEST_PASSWORD,
        model_name="account.move",
        domain=ACCOUNT_MOVE_80K_REFUND_DOMAIN,
        operation=operation,
        amount=80000,
    )
    print(result.summary_text)

    assert result.live_allowed is expected_allowed
    assert result.deterministic_allowed is expected_allowed
    assert result.has_divergence is False
    assert {
        "miro_credit_note_approval.rule_avoir_visibilite_departement",
        "miro_credit_note_visibility_rules.rule_avoir_multi_societe",
        "miro_credit_note_visibility_rules.rule_avoir_visibilite_regionale",
        "miro_credit_note_visibility_rules.rule_avoir_visibilite_nationale",
    }.issubset({ref.xml_id for ref in result.live_rule_refs})
