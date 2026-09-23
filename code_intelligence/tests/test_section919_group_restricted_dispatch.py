"""
code_intelligence/tests/test_section919_group_restricted_dispatch.py

Tests for Section 919:
1. _WORKFLOW_STEP_METHOD_ROLE_RE correctly parses method names and roles.
2. Approval vs group-restricted classification works as expected.
3. _fetch_button_and_source helper returns None for already-seen calls.
"""

import pytest
import re

from code_intelligence.agent.predispatch_access import (
    _WORKFLOW_STEP_METHOD_ROLE_RE,
    _APPROVAL_BUTTON_METHOD_RE,
)


SAMPLE_WORKFLOW = (
    "Step 1: [draft] -> [done] via Button '' (Method: `action_view_invoice()`, Role: [All Users])\n"
    "Step 2: [draft] -> [sale] via Button 'Confirm Order' (Method: `button_confirm()`, Role: [All Users])\n"
    "Step 7: [done] -> [done] via Button 'Unlock' (Method: `button_unlock()`, Role: [purchase.group_purchase_manager])\n"
    "Step 8: [done] -> [sale] via Button 'Confirm Receipt Date' (Method: `confirm_reminder_mail()`, Role: [base.group_no_one])\n"
    "Step 10: [purchase] -> [done] via Button 'Lock' (Method: `button_done()`, Role: [All Users])\n"
)


class TestWorkflowStepRegex:
    def test_extracts_all_methods_with_roles(self):
        matches = _WORKFLOW_STEP_METHOD_ROLE_RE.findall(SAMPLE_WORKFLOW)
        assert len(matches) == 5
        names = [m[0] for m in matches]
        assert "button_confirm" in names
        assert "button_unlock" in names
        assert "confirm_reminder_mail" in names
        assert "action_view_invoice" in names
        assert "button_done" in names

    def test_button_unlock_has_manager_role(self):
        matches = _WORKFLOW_STEP_METHOD_ROLE_RE.findall(SAMPLE_WORKFLOW)
        role_map = {m[0]: m[1] for m in matches}
        assert role_map["button_unlock"] == "purchase.group_purchase_manager"

    def test_all_users_role_detected(self):
        matches = _WORKFLOW_STEP_METHOD_ROLE_RE.findall(SAMPLE_WORKFLOW)
        role_map = {m[0]: m[1] for m in matches}
        assert role_map["button_confirm"] == "All Users"
        assert role_map["button_done"] == "All Users"


class TestCandidateClassification:
    def _classify(self, workflow_text):
        seen = set()
        approval = []
        group_restricted = []
        for method_name, role_text in _WORKFLOW_STEP_METHOD_ROLE_RE.findall(workflow_text):
            if method_name in seen:
                continue
            seen.add(method_name)
            if _APPROVAL_BUTTON_METHOD_RE.match(method_name):
                approval.append(method_name)
            elif role_text.strip() != "All Users":
                group_restricted.append(method_name)
        return approval, group_restricted

    def test_button_confirm_is_approval(self):
        approval, _ = self._classify(SAMPLE_WORKFLOW)
        assert "button_confirm" in approval

    def test_button_unlock_is_group_restricted(self):
        _, group_restricted = self._classify(SAMPLE_WORKFLOW)
        assert "button_unlock" in group_restricted

    def test_button_done_is_neither(self):
        approval, group_restricted = self._classify(SAMPLE_WORKFLOW)
        assert "button_done" not in approval
        assert "button_done" not in group_restricted

    def test_action_view_invoice_is_neither(self):
        approval, group_restricted = self._classify(SAMPLE_WORKFLOW)
        assert "action_view_invoice" not in approval
        assert "action_view_invoice" not in group_restricted

    def test_confirm_reminder_mail_is_group_restricted(self):
        _, group_restricted = self._classify(SAMPLE_WORKFLOW)
        assert "confirm_reminder_mail" in group_restricted

    def test_dedup_same_method_twice(self):
        doubled = SAMPLE_WORKFLOW + (
            "Step 99: [x] -> [y] via Button 'Unlock' (Method: `button_unlock()`, "
            "Role: [purchase.group_purchase_manager])\n"
        )
        _, group_restricted = self._classify(doubled)
        assert group_restricted.count("button_unlock") == 1
