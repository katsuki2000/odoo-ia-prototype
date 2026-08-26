{
    "name": "Custom Expense Risk - Score (Adversarial Bloc 9)",
    "version": "17.0.1.0.0",
    "category": "Custom",
    "summary": "Computed risk_score on hr.expense, depending on fields declared in a SEPARATE upstream module (custom_expense_risk_base) plus a core hr_expense computed field (total_amount).",
    "depends": ["custom_expense_risk_base"],
    "data": [],
    "installable": True,
}
