"""
erp_data/tests/test_bloc_b1_evidence_search_partner.py

B1 replication of the B0 pilot pattern to a fifth ORM tool (ORM 4/9, todo/
contexte.txt sections 471+). Validates that search_partner_raw() produces
structured Evidence at the source, mirroring
test_bloc_b1_evidence_get_order_status.py's coverage of
get_order_status_raw. Pure unit tests -- connector.search_read is mocked
so these never touch a live Odoo instance, unlike the existing
@pytest.mark.integration tests in test_odoo_tools.py.

First ORM tool Evidence-ified whose underlying query is a genuine
multi-result search (`ilike` on a partial name) rather than a
single-record lookup or an aggregation -- up to 5 partners can be
displayed in `text` at once, each backed by its own Evidence.
"""

from unittest.mock import patch

from erp_data.odoo_tools import (
    search_partner_raw,
    search_partner,
    odoo_uid_ctx,
)
from core.evidence import Evidence, EvidenceSourceType


def test_search_partner_raw_returns_text_and_one_evidence_per_partner():
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.return_value = [
            {"name": "Rakoto", "email": "rakoto@x.com", "phone": "111", "city": "Tana"},
            {"name": "Randria", "email": "randria@x.com", "phone": "222", "city": "Fianar"},
        ]
        token = odoo_uid_ctx.set(7)
        try:
            text, evidence_list = search_partner_raw("Ra")
        finally:
            odoo_uid_ctx.reset(token)

    assert isinstance(text, str)
    assert "Rakoto" in text
    assert "Randria" in text
    assert isinstance(evidence_list, list)
    assert len(evidence_list) == 2
    for e in evidence_list:
        assert isinstance(e, Evidence)
        assert e.source_type == EvidenceSourceType.ORM
        assert e.source == "res.partner:search_read(name,email,phone,city)"


def test_search_partner_raw_evidence_carries_contact_fields_as_single_dict_value():
    """Design confirmed by San Goku (section 471): one Evidence per
    displayed partner, carrying email/phone/city together as a single
    structured value rather than 3 separate Evidence per partner."""
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.return_value = [
            {"name": "Rakoto", "email": "rakoto@x.com", "phone": "111", "city": "Tana"},
        ]
        token = odoo_uid_ctx.set(1)
        try:
            _text, evidence_list = search_partner_raw("Rakoto")
        finally:
            odoo_uid_ctx.reset(token)

    evidence = evidence_list[0]
    assert evidence.value == {"email": "rakoto@x.com", "phone": "111", "city": "Tana"}
    assert "Rakoto" in evidence.claim
    assert "Contact details" in evidence.claim


def test_search_partner_raw_missing_fields_display_as_na_in_both_text_and_evidence():
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.return_value = [
            {"name": "Rakoto", "email": None, "phone": None, "city": None},
        ]
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = search_partner_raw("Rakoto")
        finally:
            odoo_uid_ctx.reset(token)

    assert "N/A" in text
    assert evidence_list[0].value == {"email": "N/A", "phone": "N/A", "city": "N/A"}


def test_search_partner_raw_empty_result_produces_single_negative_evidence():
    """Even a 'no match' outcome is itself a fact worth recording as
    Evidence (absence of a match), not just silently dropped -- same
    convention already established by the other ORM tools."""
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.return_value = []
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = search_partner_raw("Personne")
        finally:
            odoo_uid_ctx.reset(token)

    assert "Aucun client trouvé" in text
    assert len(evidence_list) == 1
    evidence = evidence_list[0]
    assert evidence.value is None
    assert evidence.source_type == EvidenceSourceType.ORM
    assert evidence.claim == "No res.partner matches name=Personne"


def test_search_partner_raw_more_than_five_results_only_first_five_get_evidence():
    """Pre-existing display truncation to 5 results is unchanged -- the
    Evidence list must never cover a partner beyond that truncation, since
    text never asserts anything about the ignored matches."""
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.return_value = [
            {"name": f"Client{i}", "email": "e", "phone": "p", "city": "c"}
            for i in range(7)
        ]
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = search_partner_raw("Client")
        finally:
            odoo_uid_ctx.reset(token)

    assert len(evidence_list) == 5
    assert "précisez la recherche" in text
    assert all(e.claim != "Contact details for partner=Client5" for e in evidence_list)
    assert all(e.claim != "Contact details for partner=Client6" for e in evidence_list)


def test_search_partner_raw_no_confidence_set():
    """B0 decision (todo/contexte.txt section 426): a deterministic ORM
    read never carries a confidence score."""
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.return_value = [
            {"name": "X", "email": "x", "phone": "1", "city": "c"}
        ]
        token = odoo_uid_ctx.set(1)
        try:
            _text, evidence_list = search_partner_raw("X")
        finally:
            odoo_uid_ctx.reset(token)

    assert all(e.confidence is None for e in evidence_list)


def test_search_partner_raw_evidence_scope_carries_execution_identity():
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.return_value = [
            {"name": "X", "email": "x", "phone": "1", "city": "c"}
        ]
        token = odoo_uid_ctx.set(42)
        try:
            _text, evidence_list = search_partner_raw("X")
        finally:
            odoo_uid_ctx.reset(token)

    for e in evidence_list:
        assert e.scope["execution_identity"] == 42
        assert "read_at" in e.scope
        assert "company_id" not in e.scope  # not fabricated, see _orm_evidence_scope


def test_search_partner_tool_wrapper_unchanged_return_contract():
    """The @tool wrapper must still return a plain string."""
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.return_value = [
            {"name": "X", "email": "x", "phone": "1", "city": "c"}
        ]
        token = odoo_uid_ctx.set(1)
        try:
            result = search_partner.invoke({"nom": "X"})
        finally:
            odoo_uid_ctx.reset(token)

    assert isinstance(result, str)
    assert "X" in result


def test_search_partner_tool_wrapper_still_catches_connector_exceptions():
    """Non-regression of the original try/except: it lives in the @tool
    wrapper, not in _raw -- the observable error-string behavior on a
    connector failure must be identical to before this Evidence-ification."""
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.side_effect = RuntimeError("boom")
        token = odoo_uid_ctx.set(1)
        try:
            result = search_partner.invoke({"nom": "X"})
        finally:
            odoo_uid_ctx.reset(token)

    assert "Erreur lors de la recherche du client" in result


def test_search_partner_raw_propagates_exceptions_without_fabricating_evidence():
    """_raw must never swallow a connector exception itself -- doing so
    would risk fabricating an Evidence (e.g. a false negative) from a
    technical failure rather than a real absence of data."""
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.side_effect = RuntimeError("boom")
        token = odoo_uid_ctx.set(1)
        try:
            raised = False
            try:
                search_partner_raw("X")
            except RuntimeError:
                raised = True
        finally:
            odoo_uid_ctx.reset(token)

    assert raised
