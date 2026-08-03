"""
code_intelligence/tests/test_sourcing_guard.py

Bloc 4 / J14: mechanical sourcing verification tests.

These tests never judge a citation "by eye" -- they assert exactly what
verify_citations() and annotate_unverifiable_citations() do against
synthetic final_answer / raw_tool_output pairs, mirroring the real
mismatch classes found in the adversarial benchmark runs (bare file links
with no line range, invented xml_ids, cross-mechanism attribution).
"""

from __future__ import annotations

import pytest

from code_intelligence.sourcing_guard import (
    SourcingVerificationResult,
    annotate_unverifiable_citations,
    verify_citations,
)


# =====================================================================
# Scoped file citations (file:///path#Lstart-Lend)
# =====================================================================

def test_scoped_citation_exactly_matching_ground_truth_is_verified():
    raw = "Voir [account_move.py:L10-L25](file:///a/account_move.py#L10-L25)."
    answer = "Selon [account_move.py:L10-L25](file:///a/account_move.py#L10-L25), ..."
    result = verify_citations(answer, raw)
    assert result.is_fully_verified
    assert result.unverified_scoped_citations == []


def test_scoped_citation_narrower_than_ground_truth_is_verified():
    """The LLM may legitimately quote a narrower slice of a larger cited
    range -- this is not fabrication, it's a valid subset."""
    raw = "Voir [account_move.py:L1-L50](file:///a/account_move.py#L1-L50)."
    answer = "Selon [account_move.py:L12-L15](file:///a/account_move.py#L12-L15), ..."
    result = verify_citations(answer, raw)
    assert result.is_fully_verified


def test_scoped_citation_wider_than_ground_truth_is_unverified():
    """Widening a citation beyond what any tool actually produced is a
    fabrication, even if the file path is real and the ranges overlap."""
    raw = "Voir [account_move.py:L10-L15](file:///a/account_move.py#L10-L15)."
    answer = "Selon [account_move.py:L1-L100](file:///a/account_move.py#L1-L100), ..."
    result = verify_citations(answer, raw)
    assert not result.is_fully_verified
    assert ("a/account_move.py", 1, 100) in result.unverified_scoped_citations


def test_scoped_citation_for_unrelated_file_is_unverified():
    raw = "Voir [account_move.py:L10-L25](file:///a/account_move.py#L10-L25)."
    answer = "Selon [purchase_request.py:L10-L25](file:///a/purchase_request.py#L10-L25), ..."
    result = verify_citations(answer, raw)
    assert not result.is_fully_verified
    assert ("a/purchase_request.py", 10, 25) in result.unverified_scoped_citations


def test_scoped_citation_with_shifted_line_range_same_file_is_unverified():
    """Same file, plausible-looking range, but never actually produced --
    exactly the kind of 'plausible but unverified' citation this guard
    exists to catch."""
    raw = "Voir [hr_leave.py:L40-L60](file:///a/hr_leave.py#L40-L60)."
    answer = "Selon [hr_leave.py:L100-L120](file:///a/hr_leave.py#L100-L120), ..."
    result = verify_citations(answer, raw)
    assert not result.is_fully_verified
    assert ("a/hr_leave.py", 100, 120) in result.unverified_scoped_citations


def test_multiple_scoped_citations_mixed_verified_and_unverified():
    raw = "[a.py:L1-L10](file:///a.py#L1-L10) et [b.py:L1-L10](file:///b.py#L1-L10)."
    answer = (
        "Voir [a.py:L2-L5](file:///a.py#L2-L5), "
        "[b.py:L1-L10](file:///b.py#L1-L10), "
        "et [c.py:L1-L10](file:///c.py#L1-L10)."
    )
    result = verify_citations(answer, raw)
    assert not result.is_fully_verified
    assert ("c.py", 1, 10) in result.unverified_scoped_citations
    assert ("a.py", 2, 5) not in result.unverified_scoped_citations
    assert ("b.py", 1, 10) not in result.unverified_scoped_citations


def test_no_citations_in_either_text_is_fully_verified():
    result = verify_citations("Réponse générale sans citation.", "Aucune donnée d'outil.")
    assert result.is_fully_verified


def test_ground_truth_with_no_citations_flags_any_answer_citation():
    raw = "Le modèle account.move a des règles globales."
    answer = "Voir [x.py:L1-L5](file:///x.py#L1-L5)."
    result = verify_citations(answer, raw)
    assert not result.is_fully_verified
    assert ("x.py", 1, 5) in result.unverified_scoped_citations


# =====================================================================
# Bare file links (no line range at all)
# =====================================================================

def test_bare_file_link_is_flagged_even_if_path_is_real():
    raw = "Voir [x.py:L10-L20](file:///a/x.py#L10-L20)."
    answer = "Voir [x.py](file:///a/x.py)."
    result = verify_citations(answer, raw)
    assert not result.is_fully_verified
    assert result.bare_file_links == ["a/x.py"]
    assert result.unverified_scoped_citations == []


def test_bare_file_link_does_not_double_count_as_scoped_unverified():
    """A link entirely missing #L... must be classified as bare, not
    silently ignored by the scoped-citation regex nor double-reported."""
    raw = ""
    answer = "Voir [account_move.py](file:///a/account_move.py)."
    result = verify_citations(answer, raw)
    assert result.bare_file_links == ["a/account_move.py"]
    assert result.unverified_scoped_citations == []


def test_multiple_bare_file_links_all_reported():
    answer = "Voir [a.py](file:///a.py) et [b.py](file:///b.py)."
    result = verify_citations(answer, "")
    assert set(result.bare_file_links) == {"a.py", "b.py"}


# =====================================================================
# xml_id citations
# =====================================================================

def test_xml_id_present_in_ground_truth_is_verified():
    raw = "Règle: xml_id: custom_credit_note_visibility_rules.rule_avoir_visibilite_regionale"
    answer = "Conformément à xml_id: custom_credit_note_visibility_rules.rule_avoir_visibilite_regionale, ..."
    result = verify_citations(answer, raw)
    assert result.is_fully_verified


def test_invented_xml_id_is_unverified():
    raw = "Règle: xml_id: custom_credit_note_visibility_rules.rule_avoir_visibilite_regionale"
    answer = "Conformément à xml_id: fake_module.rule_invented, ..."
    result = verify_citations(answer, raw)
    assert not result.is_fully_verified
    assert "fake_module.rule_invented" in result.unverified_xml_ids


def test_bare_technical_identifier_without_xml_id_prefix_is_not_a_citation():
    """A bare identifier like 'account.group_account_manager' used as
    ordinary vocabulary (not prefixed 'xml_id:') is not a sourcing claim
    and must not be flagged -- only the explicit prefix form is checked."""
    raw = "Groupes: account.group_account_manager, account.group_account_user"
    answer = "Le groupe account.group_account_manager peut valider."
    result = verify_citations(answer, raw)
    assert result.is_fully_verified
    assert result.unverified_xml_ids == []


def test_multiple_xml_ids_mixed_verified_and_unverified():
    raw = "xml_id: mod_a.rule_one et xml_id: mod_b.rule_two"
    answer = "Selon xml_id: mod_a.rule_one et xml_id: mod_c.rule_fake, ..."
    result = verify_citations(answer, raw)
    assert not result.is_fully_verified
    assert result.unverified_xml_ids == ["mod_c.rule_fake"]


def test_same_xml_id_cited_twice_is_reported_once():
    raw = ""
    answer = "xml_id: mod.fake et encore xml_id: mod.fake"
    result = verify_citations(answer, raw)
    assert result.unverified_xml_ids == ["mod.fake"]


# =====================================================================
# Combined mismatch classes in a single answer
# =====================================================================

def test_answer_with_all_three_mismatch_classes_reports_all():
    raw = "xml_id: mod.real -- [ok.py:L1-L5](file:///ok.py#L1-L5)"
    answer = (
        "xml_id: mod.fake ; "
        "[bare.py](file:///bare.py) ; "
        "[wide.py:L1-L999](file:///wide.py#L1-L999)"
    )
    result = verify_citations(answer, raw)
    assert not result.is_fully_verified
    assert "mod.fake" in result.unverified_xml_ids
    assert "bare.py" in result.bare_file_links
    assert ("wide.py", 1, 999) in result.unverified_scoped_citations


# =====================================================================
# is_fully_verified property
# =====================================================================

def test_is_fully_verified_true_on_default_construction():
    assert SourcingVerificationResult().is_fully_verified


@pytest.mark.parametrize(
    "kwargs",
    [
        {"unverified_scoped_citations": [("x.py", 1, 2)]},
        {"bare_file_links": ["x.py"]},
        {"unverified_xml_ids": ["mod.fake"]},
    ],
)
def test_is_fully_verified_false_when_any_field_populated(kwargs):
    assert not SourcingVerificationResult(**kwargs).is_fully_verified


# =====================================================================
# annotate_unverifiable_citations
# =====================================================================

def test_annotate_is_noop_when_fully_verified():
    answer = "Réponse propre."
    result = SourcingVerificationResult()
    assert annotate_unverifiable_citations(answer, result) == answer


def test_annotate_appends_warning_without_altering_original_answer_text():
    answer = "Voici la réponse originale."
    result = SourcingVerificationResult(unverified_xml_ids=["mod.fake"])
    annotated = annotate_unverifiable_citations(answer, result)
    assert annotated.startswith(answer)
    assert "mod.fake" in annotated
    assert "SOURCING NON VÉRIFIÉ" in annotated


def test_annotate_mentions_all_three_mismatch_classes_when_present():
    answer = "Réponse."
    result = SourcingVerificationResult(
        unverified_scoped_citations=[("wide.py", 1, 999)],
        bare_file_links=["bare.py"],
        unverified_xml_ids=["mod.fake"],
    )
    annotated = annotate_unverifiable_citations(answer, result)
    assert "wide.py#L1-L999" in annotated
    assert "bare.py" in annotated
    assert "mod.fake" in annotated


def test_annotate_never_removes_or_rewrites_the_unverified_citation_itself():
    """The guard flags, it never silently strips content -- removing an
    unverified citation could itself introduce unreviewed text changes."""
    answer = "Selon xml_id: mod.fake, l'accès est autorisé."
    result = SourcingVerificationResult(unverified_xml_ids=["mod.fake"])
    annotated = annotate_unverifiable_citations(answer, result)
    assert "Selon xml_id: mod.fake, l'accès est autorisé." in annotated
