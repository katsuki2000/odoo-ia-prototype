"""J6: distinguish Odoo security results from runtime context effects.

These tests use the same live Odoo instance and users as J5.  They deliberately
do not synthesize another language, company, record, or date-sensitive rule.
Unavailable live dimensions are reported by the inventory test instead of
being presented as covered behavior.
"""

from __future__ import annotations

import xmlrpc.client

import pytest

from code_intelligence.odoo_rpc_client import OdooRpcClient
from code_intelligence.tests.test_j5_live_validation import (
    ACCOUNT_MOVE_80K_REFUND_DOMAIN,
    _authenticate,
)


pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "context",
    [
        {},
        {"allowed_company_ids": [1]},
        {"allowed_company_ids": [1], "lang": "en_US"},
        {"allowed_company_ids": [1], "date": "2020-01-01"},
    ],
)
def test_q6_combined_groups_are_stable_across_available_contexts(
    live_client: OdooRpcClient, context: dict
):
    """Q6.1 remains allowed; context must not be mistaken for group OR logic."""
    uid = _authenticate(live_client, "test_both_2026")
    record_ids = live_client.search_as_user(
        uid,
        "account.move",
        ACCOUNT_MOVE_80K_REFUND_DOMAIN,
        operation="read",
        limit=5,
        context=context,
    )

    assert record_ids, f"Q6.1 access changed unexpectedly under context={context!r}"


@pytest.mark.parametrize(
    "context",
    [{}, {"allowed_company_ids": [1]}],
)
def test_q6_no_group_acl_denial_is_not_a_context_effect(
    live_client: OdooRpcClient, context: dict
):
    """Q6.2 stays ACL-denied regardless of the available company context."""
    uid = _authenticate(live_client, "test_no_group_2026")

    with pytest.raises(xmlrpc.client.Fault) as excinfo:
        live_client.search_as_user(
            uid,
            "account.move",
            ACCOUNT_MOVE_80K_REFUND_DOMAIN,
            operation="read",
            limit=1,
            context=context,
        )

    fault = excinfo.value.faultString
    assert "Access Denied by ACLs" in fault or "not allowed to access" in fault


def test_active_company_context_restricts_to_authorized_company(
    live_client: OdooRpcClient,
):
    """Company context enforces the user's authorized-company boundary.

    NOTE (J6 environment limitation): odoo-dev is single-company (Company
    Alpha, id=1). This cannot validate that record VISIBILITY differs
    between two companies the user is authorized for -- that would need a
    genuine multi-company fixture with test_both_2026 granted access to a
    second company, which does not exist here. What IS validated: the
    company-context boundary is enforced at all (an authorized company
    succeeds, an unauthorized one is rejected by Odoo before any ir.rule
    evaluation happens) -- a distinct, real property, not a substitute for
    the original multi-company visibility claim. Documented here rather
    than silently asserting coverage the live environment cannot provide,
    per the same principle as
    test_live_context_inventory_does_not_overclaim_language_or_date_coverage.
    """
    uid = _authenticate(live_client, "test_both_2026")
    assert live_client.check_access_rights(uid, "account.move", "read") is True

    authorized_ids = live_client.search_as_user(
        uid,
        "account.move",
        ACCOUNT_MOVE_80K_REFUND_DOMAIN,
        context={"allowed_company_ids": [1]},
        limit=5,
    )
    assert authorized_ids

    with pytest.raises(xmlrpc.client.Fault) as excinfo:
        live_client.search_as_user(
            uid,
            "account.move",
            ACCOUNT_MOVE_80K_REFUND_DOMAIN,
            context={"allowed_company_ids": [2]},
            limit=5,
        )
    fault_msg = excinfo.value.faultString.lower()
    assert "unauthorized" in fault_msg or "invalid" in fault_msg or "access" in fault_msg or "company" in fault_msg



def test_live_context_inventory_does_not_overclaim_language_or_date_coverage(
    live_client: OdooRpcClient,
):
    """Record the live limits: no French language or date-sensitive rule exists."""
    admin_uid = live_client.authenticate_admin()
    languages = live_client.execute_kw(
        admin_uid,
        "res.lang",
        "search_read",
        [[("active", "=", True)]],
        {"fields": ["code"], "limit": 100},
    )
    rules = live_client.execute_kw(
        admin_uid,
        "ir.rule",
        "search_read",
        [[("model_id.model", "=", "account.move")]],
        {"fields": ["id", "domain_force"], "limit": 100},
    )

    active_language_codes = {row["code"] for row in languages}
    date_sensitive_rules = [
        row
        for row in rules
        if any(token in (row.get("domain_force") or "") for token in (
            "context_today",
            "context_timestamp",
            "datetime",
        ))
    ]

    print(
        "J6 live context inventory: "
        f"active_languages={sorted(active_language_codes)}, "
        f"date_sensitive_account_move_rules={[row['id'] for row in date_sensitive_rules]}"
    )
    assert "en_US" in active_language_codes
    assert "fr_FR" not in active_language_codes
    assert date_sensitive_rules == []
