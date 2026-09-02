"""
erp_data/tests/test_bloc_b1_evidence_get_recent_tickets.py

B1 replication of the B0 pilot pattern to a sixth ORM tool (ORM 6/9, todo/
contexte.txt sections 476+). Validates that get_recent_tickets_raw()
produces structured Evidence at the source, mirroring
test_bloc_b1_evidence_search_partner.py's coverage of search_partner_raw.
Pure unit tests -- connector.search_read is mocked so these never touch a
live Odoo instance, unlike the existing @pytest.mark.integration tests in
test_odoo_tools.py.

First ORM tool whose underlying flow has an early-return AMBIGUÏTÉ branch
that asserts no fact about any specific ticket -- that branch must return
an empty Evidence list. Also the first ORM tool where a fetched-but-
display-irrelevant field (date_deadline, used only for sorting) must be
deliberately excluded from Evidence, mirroring amount_total's exclusion in
get_order_status_raw.
"""

from unittest.mock import patch

from erp_data.odoo_tools import (
    get_recent_tickets_raw,
    get_recent_tickets,
    odoo_uid_ctx,
)
from core.evidence import Evidence, EvidenceSourceType


def test_get_recent_tickets_raw_returns_text_and_one_evidence_per_ticket():
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.return_value = [
            {"name": "Ticket A", "state": "01_in_progress", "create_date": "2026-08-01 10:00:00", "date_deadline": "2026-08-05", "partner_id": [1, "Client Alpha"]},
            {"name": "Ticket B", "state": "1_done", "create_date": "2026-07-20 09:00:00", "date_deadline": "2026-07-25", "partner_id": [2, "Client Beta"]},
        ]
        token = odoo_uid_ctx.set(7)
        try:
            text, evidence_list = get_recent_tickets_raw(client="", limite=0, statut=None)
        finally:
            odoo_uid_ctx.reset(token)

    assert isinstance(text, str)
    assert "Ticket A" in text
    assert "Ticket B" in text
    assert isinstance(evidence_list, list)
    assert len(evidence_list) == 2
    for e in evidence_list:
        assert isinstance(e, Evidence)
        assert e.source_type == EvidenceSourceType.ORM
        assert e.source == "project.task:search_read(state,create_date,partner_id)"


def test_get_recent_tickets_raw_evidence_carries_state_partner_create_date_as_single_dict_value():
    """Design confirmed by San Goku (section 476): one Evidence per
    displayed ticket, carrying state/partner/create_date together as a
    single structured value -- same pattern as search_partner_raw's
    contact dict."""
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.return_value = [
            {"name": "Ticket A", "state": "01_in_progress", "create_date": "2026-08-01 10:00:00", "date_deadline": "2026-08-05", "partner_id": [1, "Client Alpha"]},
        ]
        token = odoo_uid_ctx.set(1)
        try:
            _text, evidence_list = get_recent_tickets_raw(client="", limite=0, statut=None)
        finally:
            odoo_uid_ctx.reset(token)

    evidence = evidence_list[0]
    assert evidence.value == {"state": "01_in_progress", "partner": "Client Alpha", "create_date": "2026-08-01"}
    assert "Ticket A" in evidence.claim
    assert "Ticket details" in evidence.claim


def test_get_recent_tickets_raw_never_includes_date_deadline_in_evidence():
    """date_deadline is fetched and used for sorting only -- it is never
    displayed in `text`, so it must never be fabricated into Evidence,
    same discipline as amount_total's exclusion in get_order_status_raw."""
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.return_value = [
            {"name": "Ticket A", "state": "01_in_progress", "create_date": "2026-08-01 10:00:00", "date_deadline": "2026-08-05", "partner_id": [1, "Client Alpha"]},
        ]
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_recent_tickets_raw(client="", limite=0, statut=None)
        finally:
            odoo_uid_ctx.reset(token)

    assert "2026-08-05" not in text
    assert "date_deadline" not in evidence_list[0].value
    assert "2026-08-05" not in str(evidence_list[0].value)


def test_get_recent_tickets_raw_missing_fields_display_as_na_in_both_text_and_evidence():
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.return_value = [
            {"name": "Ticket X", "state": None, "create_date": None, "date_deadline": None, "partner_id": False},
        ]
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_recent_tickets_raw(client="", limite=0, statut=None)
        finally:
            odoo_uid_ctx.reset(token)

    assert "N/A" in text
    assert evidence_list[0].value == {"state": "N/A", "partner": "N/A", "create_date": "N/A"}


def test_get_recent_tickets_raw_empty_result_produces_single_negative_evidence():
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.return_value = []
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_recent_tickets_raw(client="Client Inconnu", limite=0, statut=None)
        finally:
            odoo_uid_ctx.reset(token)

    assert "Aucun ticket trouvé" in text
    assert len(evidence_list) == 1
    evidence = evidence_list[0]
    assert evidence.value is None
    assert evidence.source_type == EvidenceSourceType.ORM
    assert evidence.claim == "No project.task matches client=Client Inconnu, statut=all"


def test_get_recent_tickets_raw_ambiguity_branch_produces_no_evidence():
    """San Goku's decision (this chantier): the AMBIGUÏTÉ branch asserts
    no fact about any specific ticket -- it interrupts display to ask the
    caller to disambiguate a client -- so it must return an empty Evidence
    list, never Evidence built from the intermediate records used to
    detect the ambiguity."""
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.return_value = [
            {"name": "Ticket A", "state": "01_in_progress", "create_date": "2026-08-01", "date_deadline": "2026-08-05", "partner_id": [1, "Client Alpha SA"]},
            {"name": "Ticket B", "state": "1_done", "create_date": "2026-07-20", "date_deadline": "2026-07-25", "partner_id": [2, "Client Alpha SARL"]},
        ]
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_recent_tickets_raw(client="Alpha", limite=0, statut=None)
        finally:
            odoo_uid_ctx.reset(token)

    assert text.startswith("AMBIGUÏTÉ")
    assert evidence_list == []


def test_get_recent_tickets_raw_limite_truncation_only_displayed_tickets_get_evidence():
    """Evidence must never cover a ticket beyond display_limit, since text
    never asserts anything about the ignored matches."""
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.return_value = [
            {"name": "T1", "state": "a", "create_date": "2026-08-03", "date_deadline": "2026-08-06", "partner_id": [1, "C1"]},
            {"name": "T2", "state": "b", "create_date": "2026-08-02", "date_deadline": "2026-08-05", "partner_id": [2, "C2"]},
            {"name": "T3", "state": "c", "create_date": "2026-08-01", "date_deadline": "2026-08-04", "partner_id": [3, "C3"]},
        ]
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = get_recent_tickets_raw(client="", limite=2, statut=None)
        finally:
            odoo_uid_ctx.reset(token)

    assert len(evidence_list) == 2
    assert "Total de tickets trouvés : 3" in text
    assert all(e.claim != "Ticket details for name=T3" for e in evidence_list)


def test_get_recent_tickets_raw_no_confidence_set():
    """B0 decision (todo/contexte.txt section 426): a deterministic ORM
    read never carries a confidence score."""
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.return_value = [
            {"name": "T1", "state": "a", "create_date": "2026-08-03", "date_deadline": "2026-08-06", "partner_id": [1, "C1"]},
        ]
        token = odoo_uid_ctx.set(1)
        try:
            _text, evidence_list = get_recent_tickets_raw(client="", limite=0, statut=None)
        finally:
            odoo_uid_ctx.reset(token)

    assert all(e.confidence is None for e in evidence_list)


def test_get_recent_tickets_raw_evidence_scope_carries_execution_identity():
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.return_value = [
            {"name": "T1", "state": "a", "create_date": "2026-08-03", "date_deadline": "2026-08-06", "partner_id": [1, "C1"]},
        ]
        token = odoo_uid_ctx.set(42)
        try:
            _text, evidence_list = get_recent_tickets_raw(client="", limite=0, statut=None)
        finally:
            odoo_uid_ctx.reset(token)

    for e in evidence_list:
        assert e.scope["execution_identity"] == 42
        assert "read_at" in e.scope
        assert "company_id" not in e.scope  # not fabricated, see _orm_evidence_scope


def test_get_recent_tickets_tool_wrapper_unchanged_return_contract():
    """The @tool wrapper must still return a plain string."""
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.return_value = [
            {"name": "T1", "state": "a", "create_date": "2026-08-03", "date_deadline": "2026-08-06", "partner_id": [1, "C1"]},
        ]
        token = odoo_uid_ctx.set(1)
        try:
            result = get_recent_tickets.invoke({"client": "", "limite": 0, "statut": None})
        finally:
            odoo_uid_ctx.reset(token)

    assert isinstance(result, str)
    assert "T1" in result


def test_get_recent_tickets_tool_wrapper_still_catches_connector_exceptions():
    """Non-regression of the original try/except: it lives in the @tool
    wrapper, not in _raw -- the observable error-string behavior on a
    connector failure must be identical to before this Evidence-ification."""
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.side_effect = RuntimeError("boom")
        token = odoo_uid_ctx.set(1)
        try:
            result = get_recent_tickets.invoke({"client": "", "limite": 0, "statut": None})
        finally:
            odoo_uid_ctx.reset(token)

    assert "Erreur lors de la récupération des tickets" in result


def test_get_recent_tickets_raw_propagates_exceptions_without_fabricating_evidence():
    """_raw must never swallow a connector exception itself -- doing so
    would risk fabricating an Evidence (e.g. a false negative) from a
    technical failure rather than a real absence of data."""
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.side_effect = RuntimeError("boom")
        token = odoo_uid_ctx.set(1)
        try:
            raised = False
            try:
                get_recent_tickets_raw(client="", limite=0, statut=None)
            except RuntimeError:
                raised = True
        finally:
            odoo_uid_ctx.reset(token)

    assert raised
