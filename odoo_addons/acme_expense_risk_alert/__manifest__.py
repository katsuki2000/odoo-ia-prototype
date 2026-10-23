{
    "name": "Custom Expense Risk - Alert (Adversarial Bloc 9)",
    "version": "17.0.1.0.0",
    "category": "Custom",
    "summary": "Computed alerte_conformite on hr.expense: depends on a computed field from a SEPARATE upstream module (risk_score, acme_expense_risk_score) AND on a dotted-path field (employee_id.department_id) -- tests both cross-module compute chains and partial dependency resolution on relational sub-fields.",
    "depends": ["acme_expense_risk_score"],
    "data": [],
    "installable": True,
}
