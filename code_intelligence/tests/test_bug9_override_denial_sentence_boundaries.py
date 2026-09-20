"""
code_intelligence/tests/test_bug9_override_denial_sentence_boundaries.py

todo/contexte.txt section 842 (option 4): regression test for the latent
dotted-identifier bug in overrides.py's override-count denial guard,
structurally identical to the section-840 bug already fixed in
structure.py's module-extension-denial guard -- reproduced by direct
execution in 842, never triggered by an actual rejeu, now fixed via the
shared code_intelligence.rules.common.expand_to_sentence_bounds() helper
(option 4).
"""

from code_intelligence.rules.overrides import (
    _neutralize_override_count_denial,
    _correct_override_cascade_contradictions,
)

_RAW_OUTPUT = (
    "Cha\u00eene de surcharge de 'sale.order._action_confirm' (2 modules): "
    "1. module 'sale' -- link\n"
    "2. module 'purchase' -- link"
)


def test_dotted_model_name_in_same_sentence_is_not_swallowed():
    # Section 842 verbatim reproduction: "sale.order" contains a literal
    # '.' not followed by whitespace -- the OLD unbounded [^.\n]* prefix
    # anchored right after it and swallowed "order est le modele cible, et
    # il" into the replacement, leaving a corrupted "En resume, sale."
    # fragment. The fix must produce a clean, grammatical replacement
    # instead (whole-sentence swap is acceptable here since this is
    # genuinely all one sentence -- see the two-sentence test below for
    # the case where an EARLIER, separate sentence must survive untouched).
    answer = (
        "En r\u00e9sum\u00e9, sale.order est le mod\u00e8le cible, et il n'y a pas de "
        "surcharges d\u00e9tect\u00e9es ailleurs."
    )
    fixed = _neutralize_override_count_denial(answer, ["sale", "purchase"])
    assert "sale.\n" not in fixed
    assert not fixed.startswith("En r\u00e9sum\u00e9, sale.")
    assert "Il existe en r\u00e9alit\u00e9 2 surcharges" in fixed
    assert "'sale'" in fixed and "'purchase'" in fixed


def test_dotted_model_name_in_an_earlier_sentence_is_left_untouched():
    # A distinct, separate sentence mentioning a dotted model name BEFORE
    # the denial sentence must survive completely intact -- the real
    # period ending it (followed by a space) is the correct boundary, not
    # the internal '.' inside "sale.order" itself.
    answer = (
        "Le mod\u00e8le cible est sale.order. En r\u00e9sum\u00e9, il n'y a pas de "
        "surcharges d\u00e9tect\u00e9es ailleurs pour cette m\u00e9thode."
    )
    fixed = _neutralize_override_count_denial(answer, ["sale", "purchase"])
    assert fixed.startswith("Le mod\u00e8le cible est sale.order. ")
    assert "Il existe en r\u00e9alit\u00e9 2 surcharges" in fixed


def test_correct_override_cascade_contradictions_end_to_end():
    answer = (
        "Le mod\u00e8le cible est sale.order. En r\u00e9sum\u00e9, il n'y a pas de "
        "surcharges d\u00e9tect\u00e9es ailleurs pour cette m\u00e9thode."
    )
    fixed = _correct_override_cascade_contradictions(answer, _RAW_OUTPUT)
    assert fixed.startswith("Le mod\u00e8le cible est sale.order. ")
    assert "'sale'" in fixed and "'purchase'" in fixed
