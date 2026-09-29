from code_intelligence.rules.data_constraints import backfill_missing_conditional_check_facts

OBSERVATION = """
_sql_constraints = [
    ('accountable_required_fields',
     "CHECK(display_type IS NOT NULL OR (product_id IS NOT NULL AND product_uom IS NOT NULL AND date_planned IS NOT NULL))",
     "Missing required fields."),
    ('non_accountable_null_fields',
     "CHECK(display_type IS NULL OR (product_id IS NULL AND price_unit = 0 AND product_uom_qty = 0 AND product_uom IS NULL AND date_planned is NULL))",
     "Forbidden values."),
]
"""

INVERTED_ANSWER = """### Suppression

Une commande annulee peut etre supprimee.

### Contrainte SQL distincte

Une contrainte CHECK s'applique via `_sql_constraints` :
- Si `display_type` est non nul, `product_id`, `product_uom` et `date_planned` doivent etre remplis.
- Si `display_type` est nul, ces champs doivent etre nuls et `price_unit` vaut 0.

Cette contrainte garantit l'integrite des donnees."""

QUESTION = "quelle contrainte SQL distincte s'applique sur les lignes ?"


def test_inverted_paraphrase_is_replaced_by_exact_predicates():
    result = backfill_missing_conditional_check_facts(INVERTED_ANSWER, OBSERVATION, question=QUESTION)
    assert "doivent etre remplis" not in result
    assert "doivent etre nuls" not in result
    assert "`product_id IS NOT NULL AND product_uom IS NOT NULL AND date_planned IS NOT NULL`" in result
    assert "`product_id IS NULL AND price_unit = 0 AND product_uom_qty = 0 AND product_uom IS NULL AND date_planned is NULL`" in result


def test_unrelated_blocks_and_headings_are_kept():
    result = backfill_missing_conditional_check_facts(INVERTED_ANSWER, OBSERVATION, question=QUESTION)
    assert "Une commande annulee peut etre supprimee." in result
    assert "### Contrainte SQL distincte" in result
    assert "Cette contrainte garantit l'integrite des donnees." in result


def test_answer_with_exact_predicates_is_left_untouched():
    answer = (
        "Contrainte :\n- `display_type IS NOT NULL OR (product_id IS NOT NULL AND product_uom IS NOT NULL AND date_planned IS NOT NULL)`"
        "\n- `display_type IS NULL OR (product_id IS NULL AND price_unit = 0 AND product_uom_qty = 0 AND product_uom IS NULL AND date_planned is NULL)`"
    )
    exact = (
        "`product_id IS NOT NULL AND product_uom IS NOT NULL AND date_planned IS NOT NULL` "
        "`product_id IS NULL AND price_unit = 0 AND product_uom_qty = 0 AND product_uom IS NULL AND date_planned is NULL`"
    )
    answer = answer + "\n\n" + exact
    assert backfill_missing_conditional_check_facts(answer, OBSERVATION, question=QUESTION) == answer
