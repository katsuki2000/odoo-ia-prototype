"""
code_intelligence/tests/test_flag_ungrounded_acl_source.py

Regression, todo/contexte.txt section 550 (mandat San Goku, option a):
`_flag_ungrounded_group_xmlids()` (ci_helpers.py) used to build its
'grounded' set EXCLUSIVELY from has_group()-derived lines (the format
`analyze_security_locks` emits), so any group xml_id legitimately cited by
`who_has_access_to` (or `evaluate_record_rules`) via the 'xml_id:
module.identifier' token (utils.py::format_xml_id_citation) -- a
DIFFERENT, equally deterministic ground truth -- was wrongly flagged as
'GROUPE(S) NON VERIFIE(S)' whenever no has_group() call also existed for
the same group in that turn's tool output.

Confirmed live (todo/contexte.txt sections 547/549): PR-Q1
(custom.purchase.request WRITE ACL) produced 14 genuine ACL groups, only
one of which (purchase.group_purchase_manager, a DIFFERENT action --
validation, not write) also had a has_group() lock. The other 13 were
real, correct ACL facts mislabeled as unverified.

This file covers the fix: 'grounded' is now the union of has_group()
lines AND xml_id: citations, while a group present in NEITHER source is
still correctly flagged (no loss of protection against real hallucination).
"""

from code_intelligence.ci_helpers import _flag_ungrounded_group_xmlids


# has_group()-only source (analyze_security_locks' own line format).
_RAW_HAS_GROUP_ONLY = """\
Analyse des verrous Python ([purchase_request.py:L1-L50](file:///path/purchase_request.py#L1-L50)) [Confiance: HIGH]:
  - Groupe(s) technique(s) requis detecte(s) (has_group): purchase.group_purchase_manager
"""

# xml_id: citation-only source (who_has_access_to's own ACL matrix output,
# same token format utils.py::format_xml_id_citations emits).
_RAW_XML_ID_CITATION_ONLY = """\
Model 'custom.purchase.request' [WRITE]: Granted to base.group_user, purchase_request.group_purchase_request_manager, purchase_request.group_purchase_request_user. (xml_id: base.group_user xml_id: purchase_request.group_purchase_request_manager xml_id: purchase_request.group_purchase_request_user)
"""

# Both sources present in the same turn, disjoint groups -- the real PR-Q1 shape.
_RAW_BOTH_SOURCES = _RAW_HAS_GROUP_ONLY + "\n\n" + _RAW_XML_ID_CITATION_ONLY


class TestFlagUngroundedGroupXmlidsAclSource:
    def test_has_group_sourced_group_remains_grounded(self):
        """Unchanged behavior: a group cited only via has_group() is not flagged."""
        answer = "Le groupe requis est `purchase.group_purchase_manager`."
        result = _flag_ungrounded_group_xmlids(answer, _RAW_HAS_GROUP_ONLY)
        assert result == answer
        assert "NON VÉRIFIÉ" not in result

    def test_acl_xml_id_cited_group_is_now_grounded_not_flagged(self):
        """The section 550 fix: a group cited ONLY via who_has_access_to's
        'xml_id: ...' token (no has_group() line at all) must NOT be
        flagged -- this is the exact PR-Q1 regression."""
        answer = (
            "Les groupes `base.group_user`, "
            "`purchase_request.group_purchase_request_manager` et "
            "`purchase_request.group_purchase_request_user` ont le droit d'ecriture."
        )
        result = _flag_ungrounded_group_xmlids(answer, _RAW_XML_ID_CITATION_ONLY)
        assert result == answer
        assert "NON VÉRIFIÉ" not in result

    def test_mixed_sources_both_grounded_none_flagged(self):
        """PR-Q1's real shape: one group grounded via has_group()
        (validation), several others grounded via xml_id: citation
        (write ACL) -- none should be flagged, since each is grounded by
        its own legitimate, distinct deterministic source."""
        answer = (
            "Pour la validation, le groupe `purchase.group_purchase_manager` est requis.\n\n"
            "Pour l'ecriture, les groupes `base.group_user` et "
            "`purchase_request.group_purchase_request_manager` ont le droit."
        )
        result = _flag_ungrounded_group_xmlids(answer, _RAW_BOTH_SOURCES)
        assert result == answer
        assert "NON VÉRIFIÉ" not in result

    def test_group_in_neither_source_is_still_flagged(self):
        """No loss of protection: a group xml_id present in NEITHER
        has_group() lines NOR xml_id: citations is still a real
        hallucination risk and must still be flagged."""
        answer = (
            "Le groupe `purchase.group_purchase_manager` est requis, ainsi que "
            "`account.group_account_manager` (jamais mentionne dans les donnees)."
        )
        result = _flag_ungrounded_group_xmlids(answer, _RAW_HAS_GROUP_ONLY)
        assert "GROUPE(S) NON VÉRIFIÉ(S)" in result
        assert "account.group_account_manager" in result
        # the genuinely grounded group must not appear in the flagged list
        assert "purchase.group_purchase_manager" not in result.split(
            "GROUPE(S) NON VÉRIFIÉ(S) :"
        )[1].split(" mentionné")[0]

    def test_no_op_when_raw_output_has_no_grounding_at_all(self):
        answer = "Reponse sans aucune donnee de verrou ou d'ACL."
        result = _flag_ungrounded_group_xmlids(answer, "aucune donnee pertinente")
        assert result == answer

    def test_no_op_when_answer_mentions_no_group(self):
        answer = "Reponse qui ne cite aucun identifiant de groupe."
        result = _flag_ungrounded_group_xmlids(answer, _RAW_BOTH_SOURCES)
        assert result == answer
