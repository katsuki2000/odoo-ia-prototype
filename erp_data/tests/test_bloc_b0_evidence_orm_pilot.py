"""
erp_data/tests/test_bloc_b0_evidence_orm_pilot.py

B0 pilot (todo/contexte.txt sections 426-428): validates that
get_total_sales_raw() produces structured Evidence at the source. This is
the ORM half of the B0 pilot pair (CI half:
code_intelligence/tests/test_bloc_b0_evidence_ci_pilot.py). Pure unit
tests -- connector.read_group is mocked so these never touch a live Odoo
instance, unlike the existing @pytest.mark.integration tests in
test_odoo_tools.py.
"""

import pytest
from unittest.mock import patch

from erp_data.tools.sales import get_total_sales_raw, get_total_sales
from erp_data.odoo_context import odoo_uid_ctx
from core.evidence.evidence import Evidence, EvidenceSourceType


def test_get_total_sales_raw_returns_text_and_evidence():
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [{"amount_total": 125000.0}]
        token = odoo_uid_ctx.set(7)
        try:
            text, evidence = get_total_sales_raw(client="Rakoto", periode="", statut="toutes")
        finally:
            odoo_uid_ctx.reset(token)

    assert isinstance(text, str)
    assert "125000.00" in text
    assert isinstance(evidence, Evidence)
    assert evidence.source_type == EvidenceSourceType.ORM
    assert evidence.value == 125000.0


def test_get_total_sales_raw_evidence_scope_carries_execution_identity():
    """execution_identity must be the real requester uid, per B0's decision
    (todo/contexte.txt section 428) that it represent the identity actually
    used for the ORM read, not a decorative label."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [{"amount_total": 500.0}]
        token = odoo_uid_ctx.set(42)
        try:
            _text, evidence = get_total_sales_raw()
        finally:
            odoo_uid_ctx.reset(token)

    assert evidence.scope["execution_identity"] == 42
    assert "read_at" in evidence.scope
    assert "company_id" not in evidence.scope  # not fabricated, see _orm_evidence_scope


def test_get_total_sales_raw_no_confidence_set():
    """B0 decision (todo/contexte.txt section 426): a deterministic ORM
    read never carries a confidence score."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [{"amount_total": 500.0}]
        token = odoo_uid_ctx.set(1)
        try:
            _text, evidence = get_total_sales_raw()
        finally:
            odoo_uid_ctx.reset(token)

    assert evidence.confidence is None


def test_get_total_sales_raw_empty_result_still_produces_evidence():
    """Even a 'no data found' outcome is itself a fact worth recording as
    Evidence (absence of a match), not just silently dropped."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = []
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence = get_total_sales_raw(client="Inconnu")
        finally:
            odoo_uid_ctx.reset(token)

    assert "Aucune vente" in text
    assert evidence.value is None
    assert evidence.source_type == EvidenceSourceType.ORM


def test_get_total_sales_tool_wrapper_unchanged_return_contract():
    """The @tool wrapper must still return a plain string -- B0 explicitly
    keeps the existing tool contract intact (todo/contexte.txt section
    426, decision 1: no breaking change to the frontend/agent contract)."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [{"amount_total": 10.0}]
        token = odoo_uid_ctx.set(1)
        try:
            result = get_total_sales.invoke({"client": "", "periode": "", "statut": "toutes"})
        finally:
            odoo_uid_ctx.reset(token)

    assert isinstance(result, str)


# -----------------------------------------------------------------------------
# _resolve_statut() domain contract (todo/contexte.txt section 516)
# -----------------------------------------------------------------------------
# San Goku's mandate was explicit: text-only assertions are not enough --
# the actual `domain` sent to Odoo's read_group() must be verified for each
# statut value, not just the rendered string. These tests inspect the real
# call args passed to the mocked connector.read_group, not its return value.

@pytest.mark.parametrize("statut,expected_states", [
    ("toutes", ["draft", "sent", "sale", "done"]),
    ("confirmees", ["sale", "done"]),
    ("brouillon", ["draft", "sent"]),
    ("annulees", ["cancel"]),
])
def test_get_total_sales_raw_domain_matches_statut_contract(statut, expected_states):
    """Each statut value must produce exactly the Odoo state domain agreed
    in the contract -- in particular 'annulees' must resolve to ['cancel']
    only, not silently fall through to the 'toutes' domain (the bug this
    refactor fixed, todo/contexte.txt section 516)."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [{"amount_total": 100.0}]
        token = odoo_uid_ctx.set(1)
        try:
            get_total_sales_raw(client="", periode="", statut=statut)
        finally:
            odoo_uid_ctx.reset(token)

    called_domain = mock_read_group.call_args.kwargs["domain"]
    assert called_domain == [("state", "in", expected_states)]


def test_get_total_sales_raw_unknown_statut_falls_back_to_toutes_domain():
    """An unrecognized statut string is a defined contractual behavior
    (fallback to the 'toutes' domain), not an accidental effect of an
    else branch -- verified here against the real domain, not just prose."""
    with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [{"amount_total": 100.0}]
        token = odoo_uid_ctx.set(1)
        try:
            get_total_sales_raw(client="", periode="", statut="n'importe quoi")
        finally:
            odoo_uid_ctx.reset(token)

    called_domain = mock_read_group.call_args.kwargs["domain"]
    assert called_domain == [("state", "in", ["draft", "sent", "sale", "done"])]
