"""
code_intelligence/tests/test_section922_prose_line_unicode_hyphen.py

todo/contexte.txt section 921 (PUR-Q3), fixed in section 922: the dash
class inside _PROSE_LINE_CLAIM_PATTERN (dispatch_guards.py) was missing
U+2011 (non-breaking hyphen) and U+2010 (hyphen) -- the LLM wrote
"lignes 18\u201198" (real occurrence: lines 18-98) using the exact U+2011
character. The old class ([-\u2013\u2014] plus "\u00e0") didn't recognize
it as a range separator, so the second number never got captured and the
claim silently truncated to a single line "18", producing a false-positive
SOURCING NON VERIFIE against a real occurrence at line 19 (outside the
wrongly-narrowed 18-18 window, inside the real 18-98 one).
"""

from code_intelligence.agent.dispatch_guards import verify_citations

# Verbatim shape of the PUR-Q3 scenario: the backtick-quoted identifier
# ("purchase.order") appears literally in the dump only at line 19 -- line
# 18's "class PurchaseOrder" does not contain the substring "purchase.order"
# (case differs), so it never counts as a real occurrence.
_RAW_DUMP = (
    "  18 |     class PurchaseOrder(models.Model):\n"
    "  19 |         _name = 'purchase.order'\n"
)


def test_non_breaking_hyphen_range_is_captured_and_not_flagged():
    # U+2011 non-breaking hyphen, verbatim reproduction of the PUR-Q3 claim
    # ("lignes 18\u201198"). Before the fix this silently truncated to
    # claimed range 18-18, which does NOT cover the real occurrence at
    # line 19 -- a false-positive SOURCING NON VERIFIE. After the fix the
    # full 18-98 range is captured and correctly covers line 19.
    answer = "Voir `purchase.order` (lignes 18\u201198) pour le detail."
    result = verify_citations(answer, _RAW_DUMP)
    assert result.is_fully_verified
    assert result.prose_line_mismatches == []


def test_hyphen_variant_range_is_also_captured():
    # U+2010 hyphen, added alongside U+2011 for the same reason.
    answer = "Voir `purchase.order` (lignes 18\u201098) pour le detail."
    result = verify_citations(answer, _RAW_DUMP)
    assert result.is_fully_verified
    assert result.prose_line_mismatches == []


def test_ascii_hyphen_range_still_works_no_regression():
    answer = "Voir `purchase.order` (lignes 18-98) pour le detail."
    result = verify_citations(answer, _RAW_DUMP)
    assert result.is_fully_verified
    assert result.prose_line_mismatches == []


def test_en_dash_and_em_dash_still_work_no_regression():
    answer_en = "Voir `purchase.order` (lignes 18\u201398) pour le detail."
    answer_em = "Voir `purchase.order` (lignes 18\u201498) pour le detail."
    for answer in (answer_en, answer_em):
        result = verify_citations(answer, _RAW_DUMP)
        assert result.is_fully_verified
        assert result.prose_line_mismatches == []


def test_word_a_separator_still_works_no_regression():
    answer = "Voir `purchase.order` (lignes 18 \u00e0 98) pour le detail."
    result = verify_citations(answer, _RAW_DUMP)
    assert result.is_fully_verified
    assert result.prose_line_mismatches == []


def test_unrelated_non_breaking_hyphen_range_is_still_flagged():
    # The fix must not swallow real mismatches -- a claim using the same
    # unicode hyphen but a range that genuinely excludes the real
    # occurrence (line 19) must still be flagged.
    answer = "Voir `purchase.order` (lignes 40\u201150) pour le detail."
    result = verify_citations(answer, _RAW_DUMP)
    assert not result.is_fully_verified
    assert result.prose_line_mismatches == [
        ("purchase.order", 40, 50, (19,))
    ]


def test_old_truncated_range_would_have_been_a_false_positive():
    # Direct demonstration of the bug this fix removes: the OLD behavior
    # (claim silently truncated to a single line by the missing hyphen
    # class) is what produced the false positive -- asserting it here
    # documents the exact failure mode being closed, on the same
    # single-line form the truncation used to collapse into.
    answer = "Voir `purchase.order` (lignes 18) pour le detail."
    result = verify_citations(answer, _RAW_DUMP)
    assert not result.is_fully_verified
    assert result.prose_line_mismatches == [
        ("purchase.order", 18, 18, (19,))
    ]
