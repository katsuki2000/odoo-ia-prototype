from code_intelligence.rules.data_constraints import enforce_sql_constraint_fidelity


SOURCE = """Analyse des contraintes de données (Semgrep) pour 'purchase.order.line':
  - [purchase_order_line.py:L10-L20](file:///addons/purchase_order_line.py#L10-L20) (odoo-sql-constraints-declaration): Odoo _sql_constraints declaration detected.
    _sql_constraints = [('accountable_required_fields', 'CHECK(display_type IS NOT NULL OR product_id IS NOT NULL)', ''), ('non_accountable_null_fields', 'CHECK(display_type IS NULL OR price_unit = 0)', '')]
"""


def test_replaces_fabricated_sql_summary_when_real_declarations_are_omitted():
    answer = "Les quantités doivent être positives et le produit unique par commande."
    result = enforce_sql_constraint_fidelity(
        answer, SOURCE, "Quelles sont les contraintes SQL de purchase.order.line ?"
    )
    assert "La synthèse ne reprend pas fidèlement" in result
    assert "accountable_required_fields" in result
    assert "non_accountable_null_fields" in result
    assert "Les quantités doivent être positives" not in result


def test_keeps_synthesis_when_all_constraint_names_are_present():
    answer = "La contrainte accountable_required_fields impose le contrôle principal. La contrainte non_accountable_null_fields couvre l'autre branche."
    assert enforce_sql_constraint_fidelity(answer, SOURCE, "Explique la contrainte SQL") == answer


def test_does_not_override_unrelated_answers():
    answer = "Le bouton est grisé."
    assert enforce_sql_constraint_fidelity(answer, SOURCE, "Pourquoi le bouton est grisé ?") == answer


def test_marks_fallback_as_non_exhaustive_when_observation_was_truncated():
    result = enforce_sql_constraint_fidelity(
        "Le produit doit être unique.", SOURCE + "[TRUNCATED]", "Explique la contrainte SQL"
    )
    assert "ne garantit pas l'exhaustivité" in result
