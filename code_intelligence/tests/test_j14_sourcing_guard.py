"""
miro-rag/code_intelligence/tests/test_j14_sourcing_guard.py

Unit tests for J14 Sourcing Guard (code_intelligence/sourcing_guard.py).
Mechanically verifies file citation ranges, bare file links, and xml_id citations.
"""

from code_intelligence.ci_agent_node.guards.sourcing_guard import (
    verify_citations,
    annotate_unverifiable_citations,
)


def test_unverified_xml_id_in_final_answer_is_flagged():
    raw = "xml_id: custom_credit_note_visibility_rules.rule_avoir_visibilite_regionale ..."
    answer = "... conformément à xml_id: fake_module.rule_invented ..."
    result = verify_citations(answer, raw)
    assert not result.is_fully_verified
    assert "fake_module.rule_invented" in result.unverified_xml_ids

    annotated = annotate_unverifiable_citations(answer, result)
    assert " SOURCING NON VÉRIFIÉ " in annotated
    assert "fake_module.rule_invented" in annotated


def test_bare_file_link_is_flagged_even_if_path_is_real():
    raw = "voir [x.py:L10-L20](file:///a/x.py#L10-L20)"
    answer = "voir [x.py](file:///a/x.py)"
    result = verify_citations(answer, raw)
    assert not result.is_fully_verified
    assert result.bare_file_links == ["a/x.py"]

    annotated = annotate_unverifiable_citations(answer, result)
    assert "lien(s) fichier sans plage de lignes" in annotated


def test_scoped_subset_citation_is_verified():
    raw = "voir [x.py:L1-L50](file:///a/x.py#L1-L50) et xml_id: account.group_account_manager"
    answer = "voir [x.py:L10-L12](file:///a/x.py#L10-L12) et xml_id: account.group_account_manager"
    result = verify_citations(answer, raw)
    assert result.is_fully_verified

    annotated = annotate_unverifiable_citations(answer, result)
    assert " SOURCING NON VÉRIFIÉ" not in annotated
