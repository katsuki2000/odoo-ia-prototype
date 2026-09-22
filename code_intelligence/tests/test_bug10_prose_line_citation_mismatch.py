"""
code_intelligence/tests/test_bug10_prose_line_citation_mismatch.py

todo/contexte.txt section 891 (SAL-Q1, discovered via section 890): the
citation-verification apparatus (verify_citations, plus the stronger
substitute-or-strip mechanism in sections 870-873) only ever looks at
markdown `[text](file:///...#L-L)` links or fenced code blocks. A plain
PROSE line-number claim -- "la regle `sale_order_personal_rule` (xml_id:
..., lignes 108-113)" -- goes through neither, so it was invisible to
every existing check even though, on the real rejeu, all 4 such claims
in the answer were fabricated (real range 44-49) while the content
attributed to the identifier (domain_force, group) was verbatim correct.

section_872/873's def/class-span check (source_definitions.py) is
Python/AST-only and cannot cover this XML `<record id="...">` case either,
so this is a genuinely new, narrow, deliberately low-false-positive check:
it only fires when a backtick-quoted identifier is found ELSEWHERE in this
turn's raw tool output inside a real read_precise_source_code-style
numbered dump ("{i:4d} | {line}"), and the claimed range does not overlap
that real occurrence. An identifier that cannot be found in any numbered
dump is silently skipped -- not flagged -- to avoid flagging every
unconfirmable "ligne N" mention in ordinary prose.
"""

from code_intelligence.agent.dispatch_guards import (
    verify_citations,
    annotate_unverifiable_citations,
)

# A minimal read_precise_source_code-style numbered dump, matching the
# real SAL-Q1 case (sale_order_personal_rule genuinely at lines 44-49).
_RAW_DUMP = (
    "  44 |     <record id=\"sale_order_personal_rule\" model=\"ir.rule\">\n"
    "  45 |         <field name=\"name\">Personal Orders</field>\n"
    "  46 |         <field ref=\"model_sale_order\" name=\"model_id\"/>\n"
    "  47 |         <field name=\"domain_force\">['|',('user_id','=',user.id),('user_id','=',False)]</field>\n"
    "  48 |         <field name=\"groups\" eval=\"[(4, ref('sales_team.group_sale_salesman'))]\"/>\n"
    "  49 |     </record>\n"
)


def test_prose_line_claim_contradicting_real_dump_is_flagged():
    answer = (
        "La règle `sale_order_personal_rule` (xml_id : `sale_order_personal_rule`, "
        "lignes 108-113) applique le domaine ['|',('user_id','=',user.id),('user_id','=',False)]."
    )
    result = verify_citations(answer, _RAW_DUMP)
    assert not result.is_fully_verified
    assert result.prose_line_mismatches == [
        ("sale_order_personal_rule", 108, 113, (44,))
    ]

    annotated = annotate_unverifiable_citations(answer, result)
    assert "référence(s) de ligne en prose contredite" in annotated
    assert "108-113" in annotated and "44" in annotated


def test_prose_line_claim_matching_real_dump_is_not_flagged():
    answer = "Voir `sale_order_personal_rule` (lignes 44-49) pour le domaine complet."
    result = verify_citations(answer, _RAW_DUMP)
    assert result.is_fully_verified
    assert result.prose_line_mismatches == []


def test_single_line_claim_inside_real_range_is_not_flagged():
    """A single-line claim ('ligne 44') that falls anywhere inside the
    real multi-line occurrence is a legitimate narrowing, not a mismatch."""
    answer = "Voir `sale_order_personal_rule`, ligne 44."
    result = verify_citations(answer, _RAW_DUMP)
    assert result.is_fully_verified


def test_identifier_absent_from_any_dump_is_silently_skipped():
    """Cannot confirm either way -- must NOT be flagged, per the explicit
    false-positive concern raised before this check was built (section 890)."""
    answer = "Voir `some_other_rule_never_read`, lignes 1-5."
    result = verify_citations(answer, _RAW_DUMP)
    assert result.is_fully_verified
    assert result.prose_line_mismatches == []


def test_bare_line_mention_without_backtick_identifier_is_not_flagged():
    """Ordinary prose ('cette regle est definie ligne 108') with no
    backtick-quoted identifier attached is not a citation claim at all --
    must never be flagged, this is exactly the noise pmm wanted avoided."""
    answer = "Cette règle est définie ligne 108, juste après la règle précédente."
    result = verify_citations(answer, _RAW_DUMP)
    assert result.is_fully_verified


def test_does_not_regress_existing_uncited_code_block_check():
    """Sanity: the new check is additive, the pre-existing fenced-code-block
    check (section 814/846) still fires on its own known pattern."""
    answer = (
        "```python\n"
        "@api.constrains('name')\n"
        "def _check_name(self):\n"
        "    raise ValidationError('x')\n"
        "```\n"
    )
    result = verify_citations(answer, "no citations anywhere")
    assert not result.is_fully_verified
    assert len(result.uncited_code_blocks) == 1
