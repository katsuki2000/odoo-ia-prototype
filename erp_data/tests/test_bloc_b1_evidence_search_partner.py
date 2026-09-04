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


def test_search_partner_raw_domain_excludes_internal_user_accounts():
    """todo/contexte.txt section 528/529: res.partner mixes commercial
    contacts with internal/portal login accounts. Verified live that
    customer_rank is not a reliable discriminator on this instance's data
    (false positive on an internal account, false negatives on real
    clients) -- user_ids=False is. Domain must always carry this filter
    alongside the name search."""
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.return_value = []
        token = odoo_uid_ctx.set(1)
        try:
            search_partner_raw("Air")
        finally:
            odoo_uid_ctx.reset(token)

    called_domain = mock_search_read.call_args.kwargs["domain"]
    assert ("user_ids", "=", False) in called_domain


def test_search_partner_raw_empty_nom_defaults_and_lists_all_clients():
    """todo/contexte.txt section 531: 'combien de clients a-t-on ?' routed
    to get_sale_details instead of search_partner because nom had no
    default -- nothing told the LLM that an empty nom means 'all clients'.
    Fix is signature/docstring only (nom: str = ""); domain/presentation
    unchanged (San Goku, section 531: keep the validated user_ids filter
    exactly as-is). This test locks that nom='' still reaches
    connector.search_read with the same ilike+user_ids domain shape, called
    both explicitly and via the new default."""
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.return_value = []
        token = odoo_uid_ctx.set(1)
        try:
            search_partner_raw()
            explicit_domain = None
            search_partner_raw("")
            explicit_domain = mock_search_read.call_args.kwargs["domain"]
        finally:
            odoo_uid_ctx.reset(token)

    assert ("name", "ilike", "") in explicit_domain
    assert ("user_ids", "=", False) in explicit_domain
    assert mock_search_read.call_count == 4  # 2 invocations x (res.company + res.partner) since section 536


def test_search_partner_raw_excludes_self_company_partners_from_domain():
    """todo/contexte.txt section 535/536: search_partner_raw first reads
    res.company (whitelisted with explicit maitre de stage sign-off, see
    odoo_connector.ALLOWED_MODELS) to collect every partner_id ever
    referenced by a company, and excludes those from the res.partner
    search domain. Verified live (536) that self-company partners (e.g.
    'Company Alpha', id 7) pass the pre-existing user_ids=False filter
    just like a real client would, since they carry no user_ids either.
    This test locks that the res.company partner_ids actually reach the
    res.partner domain as an ('id', 'not in', [...]) clause."""
    def fake_search_read(uid, model, domain, fields, **kwargs):
        if model == "res.company":
            return [
                {"partner_id": [7, "Company Alpha"]},
                {"partner_id": [1, "My Company"]},
            ]
        return []

    with patch("erp_data.odoo_tools.connector.search_read", side_effect=fake_search_read) as mock_search_read:
        token = odoo_uid_ctx.set(1)
        try:
            search_partner_raw("")
        finally:
            odoo_uid_ctx.reset(token)

    partner_calls = [c for c in mock_search_read.call_args_list if c.kwargs.get("model") == "res.partner"]
    assert len(partner_calls) == 1
    called_domain = partner_calls[0].kwargs["domain"]
    assert ("id", "not in", [7, 1]) in called_domain
    assert ("user_ids", "=", False) in called_domain


def test_search_partner_raw_company_read_uses_active_test_false_context():
    """todo/contexte.txt section 538: verified live (odoo-bin shell) that
    'My Company' is a real but archived (active=False) res.company, not an
    orphaned partner as first assumed in section 536. Odoo's default
    active_test=True would silently omit it from the res.company read,
    letting its partner slip back into search_partner's results despite
    the exclusion mechanism. This locks that the res.company call always
    carries context={'active_test': False} so archived companies are seen
    too."""
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.return_value = []
        token = odoo_uid_ctx.set(1)
        try:
            search_partner_raw("")
        finally:
            odoo_uid_ctx.reset(token)

    company_calls = [c for c in mock_search_read.call_args_list if c.kwargs.get("model") == "res.company"]
    assert len(company_calls) == 1
    assert company_calls[0].kwargs.get("context") == {"active_test": False}


def test_search_partner_raw_no_company_exclusion_clause_when_no_companies():
    """When res.company returns nothing (or entries with no partner_id),
    no fabricated ('id', 'not in', []) clause should ever be appended --
    an empty exclusion list is a no-op, not a real filter."""
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.return_value = []
        token = odoo_uid_ctx.set(1)
        try:
            search_partner_raw("")
        finally:
            odoo_uid_ctx.reset(token)

    called_domain = mock_search_read.call_args.kwargs["domain"]
    assert not any(clause[0] == "id" and clause[1] == "not in" for clause in called_domain)


def test_search_partner_tool_wrapper_callable_without_args():
    """The @tool wrapper must also accept no args (LangChain sees nom as
    optional now) -- mirrors the other client-scoped tools' 'client: str =
    \"\"' convention (get_total_sales, get_sale_details, etc.)."""
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.return_value = [
            {"name": "Air Madagascar", "email": "e", "phone": "p", "city": "c"}
        ]
        token = odoo_uid_ctx.set(1)
        try:
            result = search_partner.invoke({})
        finally:
            odoo_uid_ctx.reset(token)

    assert isinstance(result, str)
    assert "Air Madagascar" in result


def test_search_partner_raw_default_limite_zero_shows_all_no_truncation():
    """todo/contexte.txt section 533: hardcoded records[:5] replaced by a
    limite param (0 = no cap), same convention as get_sale_details_raw/
    get_recent_tickets_raw. Default call (no limite passed) must now show
    every matching partner, with one Evidence per displayed partner and no
    truncation message."""
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

    assert len(evidence_list) == 7
    assert "précisez la recherche" not in text
    assert any(e.claim == "Contact details for partner=Client6" for e in evidence_list)


def test_search_partner_raw_explicit_limite_still_truncates_with_evidence_bounded():
    """A positive limite still caps display and Evidence together, same
    discipline as before section 533 (just now opt-in via the param
    instead of a hardcoded 5)."""
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.return_value = [
            {"name": f"Client{i}", "email": "e", "phone": "p", "city": "c"}
            for i in range(7)
        ]
        token = odoo_uid_ctx.set(1)
        try:
            text, evidence_list = search_partner_raw("Client", limite=5)
        finally:
            odoo_uid_ctx.reset(token)

    assert len(evidence_list) == 5
    assert "précisez la recherche" in text
    assert all(e.claim != "Contact details for partner=Client5" for e in evidence_list)
    assert all(e.claim != "Contact details for partner=Client6" for e in evidence_list)


def test_search_partner_tool_wrapper_forwards_limite():
    """The @tool wrapper must forward limite to search_partner_raw, not
    just nom."""
    with patch("erp_data.odoo_tools.connector.search_read") as mock_search_read:
        mock_search_read.return_value = [
            {"name": f"Client{i}", "email": "e", "phone": "p", "city": "c"}
            for i in range(7)
        ]
        token = odoo_uid_ctx.set(1)
        try:
            result = search_partner.invoke({"nom": "Client", "limite": 3})
        finally:
            odoo_uid_ctx.reset(token)

    assert "3 client" not in result  # sanity: total_count (7) must not be conflated with limite (3)
    assert "7 client(s) trouvé(s)" in result
    assert "précisez la recherche" in result


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
