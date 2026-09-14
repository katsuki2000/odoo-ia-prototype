"""
code_intelligence/tests/test_semantic_tags.py

Bloc P2 (todo/plan.md), Jour 1: locks the closed tag vocabulary against
todo/architecture.md (Couche 3 -- Couche semantique) so any future edit
to either the enums or the architecture doc that drifts from the other is
caught immediately -- same discipline as
test_h1c_sticky_routing.py::test_valid_routes_set_matches_queryroute_enum
for QueryRoute.
"""

from code_intelligence.rules.ontology import BehavioralTag, TechnicalTag


# Verbatim from todo/architecture.md, Couche 3 -- Couche semantique.
EXPECTED_BEHAVIORAL_TAGS = {
    "visibility_rule",
    "blocking_rule",
    "calculation_rule",
    "workflow_rule",
    "approval_rule",
    "notification_rule",
}

EXPECTED_TECHNICAL_TAGS = {
    "record_rule",
    "acl",
    "constraint",
    "computed_field",
    "server_action",
    "cron",
}


def test_behavioral_tag_matches_architecture_md_exactly():
    actual = {tag.value for tag in BehavioralTag}
    assert actual == EXPECTED_BEHAVIORAL_TAGS


def test_technical_tag_matches_architecture_md_exactly():
    actual = {tag.value for tag in TechnicalTag}
    assert actual == EXPECTED_TECHNICAL_TAGS


def test_behavioral_and_technical_vocabularies_never_overlap():
    """The two enums classify orthogonal dimensions (what vs. how) -- a
    string should never be a valid member of both, or a caller could
    silently confuse the two classifications."""
    assert EXPECTED_BEHAVIORAL_TAGS.isdisjoint(EXPECTED_TECHNICAL_TAGS)


def test_tags_are_str_enum_members_usable_as_plain_strings():
    """(str, Enum), same pattern as QueryRoute (core/schemas.py) -- a tag
    must compare equal to and be usable anywhere its plain string value
    is expected (e.g. JSON serialization of a future node attribute)."""
    assert BehavioralTag.APPROVAL_RULE == "approval_rule"
    assert TechnicalTag.RECORD_RULE == "record_rule"
