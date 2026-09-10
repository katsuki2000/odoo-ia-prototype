#!/usr/bin/env python3
"""
scripts/test_benchmark_tools.py

Interactive testing script for Code Intelligence security and rule evaluation tools.
Executes verification across adversarial test questions Q2.1, Q3.1, Q5.1, Q6.1/Q6.2, and Q9.1.
"""

import sys
from pathlib import Path

# Add project root and miro-rag to PYTHONPATH
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "miro-rag"))

from scripts.extract_modules import run_pipeline
from code_intelligence.agent.ci_agent_node.context.agent_tools import (
    set_graph_ref,
    evaluate_record_rules,
    analyze_server_actions,
    analyze_security_locks,
)

ADVERSARIAL_MODULES = [
    "custom_credit_note_approval",
    "custom_credit_note_approval_regional",
    "custom_credit_note_approval_vip",
    "custom_hr_leave_workflow",
    "custom_purchase_request",
    "custom_asset_loan",
    "custom_automation_traps",
    "custom_credit_note_visibility_rules",
    "custom_expense_reimbursement_indirect",
]


def run_interactive_tests():
    from config.settings import CUSTOM_ADDONS_PATH, CORE_ADDONS_PATH
    addons_dir = Path(CUSTOM_ADDONS_PATH) if Path(CUSTOM_ADDONS_PATH).exists() else Path(CORE_ADDONS_PATH)
    output_dir = project_root / "tmp_test_graph"

    print("=" * 80)
    print(" INTERACTIVE TEST RUNNER FOR CODE INTELLIGENCE TOOLS ")
    print("=" * 80)

    G, registry = run_pipeline(addons_dir, ADVERSARIAL_MODULES, output_dir)
    set_graph_ref(G)

    print("\n" + "=" * 80)
    print(" [Q2.1] Leave Error Message (ValidationError / UserError)")
    print("=" * 80)
    print(analyze_security_locks.invoke({"model_name": "hr.leave"}))

    print("\n" + "=" * 80)
    print(" [Q3.1] Hardcoded Email Bypass (_VALIDATEURS_EXCEPTIONNELS)")
    print("=" * 80)
    print(analyze_security_locks.invoke({"model_name": "custom.purchase.request"}))

    print("\n" + "=" * 80)
    print(" [Q5.1] Server Action Sudo Bypass & Hardcoded IDs (ir.actions.server)")
    print("=" * 80)
    print(analyze_server_actions.invoke({"model_name": "account.move"}))

    print("\n" + "=" * 80)
    print(" [Q6.1 & Q6.2] Record Rules AND/OR Engine (ir.rule)")
    print("=" * 80)
    print(
        evaluate_record_rules.invoke({
            "model_name": "account.move",
            "permission": "read",
            "user_groups_json": '["account.group_account_user"]',
        })
    )

    print("\n" + "=" * 80)
    print(" [Q9.1] Dynamic Uncertainty (getattr)")
    print("=" * 80)
    print(analyze_security_locks.invoke({"model_name": "custom.reimbursement.request"}))
    print("=" * 80)


if __name__ == "__main__":
    run_interactive_tests()
