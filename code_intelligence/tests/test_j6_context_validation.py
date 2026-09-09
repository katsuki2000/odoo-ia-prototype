"""J6: distinguish Odoo security results from runtime context effects.

These tests use the same live Odoo instance and users as J5.  They deliberately
do not synthesize another language, company, record, or date-sensitive rule.
Unavailable live dimensions are reported by the inventory test instead of
being presented as covered behavior.
"""

from __future__ import annotations

import xmlrpc.client

import pytest

from code_intelligence.live.rpc_client import OdooRpcClient
from code_intelligence.tests.test_j5_live_validation import (
    ACCOUNT_MOVE_80K_REFUND_DOMAIN,
    _authenticate,
)


pytestmark = pytest.mark.integration


CONTEXT_VARIANTS = [
    ("no_context", lambda alpha_id: {}),
    ("company_only", lambda alpha_id: {"allowed_company_ids": [alpha_id]}),
    ("company_and_lang", lambda alpha_id: {"allowed_company_ids": [alpha_id], "lang": "en_US"}),
    ("company_and_date", lambda alpha_id: {"allowed_company_ids": [alpha_id], "date": "2020-01-01"}),
]


@pytest.mark.parametrize(
    "context_builder",
    [builder for _, builder in CONTEXT_VARIANTS],
    ids=[label for label, _ in CONTEXT_VARIANTS],
)
def test_q6_combined_groups_are_stable_across_available_contexts(
    live_client: OdooRpcClient, alpha_company_id: int, context_builder
):
    """Q6.1 remains allowed; context must not be mistaken for group OR logic."""
    uid = _authenticate(live_client, "test_both_2026")
    context = context_builder(alpha_company_id)
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
    "context_builder",
    [lambda cid: {}, lambda cid: {"allowed_company_ids": [cid]}],
    ids=["no_context", "with_invalid_company"],
)
def test_q6_no_group_acl_denial_is_not_a_context_effect(
    live_client: OdooRpcClient, invalid_company_id: int, context_builder
):
    """Q6.2 stays ACL-denied regardless of the available company context."""
    uid = _authenticate(live_client, "test_no_group_2026")
    context = context_builder(invalid_company_id)

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
    live_client: OdooRpcClient, alpha_company_id: int, invalid_company_id: int,
):
    """Company context enforces the user's authorized-company boundary.

    NOTE : odoo-dev est reellement mono-societe (Company Alpha -- decision
    utilisateur, todo/contexte.txt section 321/322 ; 'My Company' a ete
    archivee). Ce test ne peut donc plus valider une difference de
    VISIBILITE entre deux societes reellement autorisees -- ca demanderait
    un fixture multi-societe explicite avec test_both_2026 autorise sur une
    seconde societe, qui n'existe plus par choix de conception. Ce qui EST
    valide : la frontiere de contexte societe est bien appliquee (une
    societe autorisee reussit, un id de societe invalide est rejete par
    Odoo avant toute evaluation ir.rule) -- une propriete distincte et
    reelle, pas un substitut a la revendication de visibilite multi-societe
    originale. alpha_company_id et invalid_company_id sont resolus
    dynamiquement (jamais un id code en dur), cf. conftest.py.
    """
    uid = _authenticate(live_client, "test_both_2026")
    assert live_client.check_access_rights(uid, "account.move", "read") is True

    authorized_ids = live_client.search_as_user(
        uid,
        "account.move",
        ACCOUNT_MOVE_80K_REFUND_DOMAIN,
        context={"allowed_company_ids": [alpha_company_id]},
        limit=5,
    )
    assert authorized_ids

    with pytest.raises(xmlrpc.client.Fault) as excinfo:
        live_client.search_as_user(
            uid,
            "account.move",
            ACCOUNT_MOVE_80K_REFUND_DOMAIN,
            context={"allowed_company_ids": [invalid_company_id]},
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
