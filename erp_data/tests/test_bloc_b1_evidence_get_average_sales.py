"""
erp_data/tests/test_bloc_b1_evidence_get_average_sales.py

B1 replication of the B0 pilot pattern to a second ORM tool (ORM 1/9, todo/
contexte.txt sections 429/465+). Validates that get_average_sales_raw()
produces structured Evidence at the source, mirroring
test_bloc_b0_evidence_orm_pilot.py's coverage of get_total_sales_raw.
Pure unit tests -- connector.read_group is mocked so these never touch a
live Odoo instance, unlike the existing @pytest.mark.integration tests in
test_odoo_tools.py.
"""

from unittest.mock import patch

from erp_data.odoo_tools import (
    get_average_sales_raw,
    get_average_sales,
    odoo_uid_ctx,
)
from core.evidence import Evidence, EvidenceSourceType


def test_get_average_sales_raw_returns_text_and_evidence_global():
    with patch("erp_data.odoo_tools.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [{"amount_total": 4200.5}]
        token = odoo_uid_ctx.set(3)
        try:
            text, evidence = get_average_sales_raw(client="", periode="toutes")
        finally:
            odoo_uid_ctx.reset(token)

    assert isinstance(text, str)
    assert "4200.50" in text
    assert isinstance(evidence, Evidence)
    assert evidence.source_type == EvidenceSourceType.ORM
    assert evidence.value == 4200.5
    assert evidence.source == "sale.order:read_group(amount_total:avg)"


def test_get_average_sales_raw_returns_text_and_evidence_per_client():
    with patch("erp_data.odoo_tools.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [{"amount_total": 999.99, "partner_id": [5, "Rakoto"]}]
        token = odoo_uid_ctx.set(9)
        try:
            text, evidence = get_average_sales_raw(client="Rakoto", periode="toutes")
        finally:
            odoo_uid_ctx.reset(token)

    assert "Rakoto" in text
    assert "999.99" in text
    assert evidence.value == 999.99
    assert "client=Rakoto" in evidence.claim


def test_get_average_sales_raw_empty_result_produces_negative_evidence():
    """Even a 'no data found' outcome is itself a fact worth recording as
    Evidence (absence of a match), not just silently dropped -- same
    convention already established by get_total_sales_raw."""
    with patch("erp_data.odoo_tools.connector.read_group") as mock_read_group:
        mock_read_group.return_value = []
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence = get_average_sales_raw(client="Personne", periode="toutes")
        finally:
            odoo_uid_ctx.reset(token)

    assert "Aucune vente trouvée" in text
    assert evidence.value is None
    assert evidence.source_type == EvidenceSourceType.ORM
    assert "No sale.order matches" in evidence.claim


def test_get_average_sales_raw_no_confidence_set():
    """B0 decision (todo/contexte.txt section 426): a deterministic ORM
    read never carries a confidence score."""
    with patch("erp_data.odoo_tools.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [{"amount_total": 500.0}]
        token = odoo_uid_ctx.set(1)
        try:
            _text, evidence = get_average_sales_raw()
        finally:
            odoo_uid_ctx.reset(token)

    assert evidence.confidence is None


def test_get_average_sales_raw_evidence_scope_carries_execution_identity():
    with patch("erp_data.odoo_tools.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [{"amount_total": 500.0}]
        token = odoo_uid_ctx.set(42)
        try:
            _text, evidence = get_average_sales_raw()
        finally:
            odoo_uid_ctx.reset(token)

    assert evidence.scope["execution_identity"] == 42
    assert "read_at" in evidence.scope
    assert "company_id" not in evidence.scope  # not fabricated, see _orm_evidence_scope


def test_get_average_sales_tool_wrapper_unchanged_return_contract():
    """The @tool wrapper must still return a plain string -- same contract
    guarantee already established for get_total_sales."""
    with patch("erp_data.odoo_tools.connector.read_group") as mock_read_group:
        mock_read_group.return_value = [{"amount_total": 10.0}]
        token = odoo_uid_ctx.set(1)
        try:
            result = get_average_sales.invoke({"client": "", "periode": "toutes"})
        finally:
            odoo_uid_ctx.reset(token)

    assert isinstance(result, str)
    assert "10.00" in result


def test_get_average_sales_tool_wrapper_still_catches_connector_exceptions():
    """Non-regression of the original try/except: it now lives in the
    @tool wrapper instead of _raw (arbitration point 1, todo/contexte.txt
    section 466), but the observable error-string behavior on a connector
    failure must be identical to before this refactor."""
    with patch("erp_data.odoo_tools.connector.read_group") as mock_read_group:
        mock_read_group.side_effect = RuntimeError("boom")
        token = odoo_uid_ctx.set(1)
        try:
            result = get_average_sales.invoke({"client": "", "periode": "toutes"})
        finally:
            odoo_uid_ctx.reset(token)

    assert "Erreur lors du calcul de la moyenne" in result


def test_get_average_sales_raw_propagates_exceptions_without_fabricating_evidence():
    """_raw must never swallow a connector exception itself -- doing so
    would risk fabricating an Evidence (e.g. a false negative) from a
    technical failure rather than a real absence of data, the same
    honesty concern already flagged for the Semgrep NO_MATCH/
    EXECUTION_ERROR ambiguity in tool 10/24."""
    with patch("erp_data.odoo_tools.connector.read_group") as mock_read_group:
        mock_read_group.side_effect = RuntimeError("boom")
        token = odoo_uid_ctx.set(1)
        try:
            raised = False
            try:
                get_average_sales_raw(client="", periode="toutes")
            except RuntimeError:
                raised = True
        finally:
            odoo_uid_ctx.reset(token)

    assert raised
