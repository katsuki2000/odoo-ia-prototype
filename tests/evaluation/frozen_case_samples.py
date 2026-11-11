"""Shared sample case for the evaluation protocol tests."""

import copy

RAW = {
    "case_id": "access_sale_manager_read",
    "split": "held_out",
    "instance": "sales_purchase_stock",
    "user_context": {
        "user": "base.user_demo",
        "company": "base.main_company",
        "language": "en_US",
        "groups": ["sales_team.group_sale_manager"],
    },
    "question": "Can a sales manager read a quotation?",
    "module": "sale",
    "expected_intent": "governance_security",
    "expected_sources": ["code"],
    "expected_objects": ["model:sale.order", "group:sales_team.group_sale_manager"],
    "acceptable_evidence": [{"kind": "graph", "source": "model:sale.order"}],
    "expected_claims": [
        {"claim_id": "c1", "statement": "Sales managers can read quotations",
         "all_of": ["sales manager"], "any_of": [["read", "view"]]},
    ],
    "abstention_rule": "none",
    "ground_truth": {"author": "reviewer", "method": "human_review", "reference": ""},
}


def make_case(case_id: str = None, **changes) -> dict:
    row = copy.deepcopy(RAW)
    if case_id:
        row["case_id"] = case_id
    row.update(changes)
    return row
