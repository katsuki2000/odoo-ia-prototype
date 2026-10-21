"""Mid-loop reminder to read the Python guard before concluding on approval questions."""

import unittest

from code_intelligence.agent.dispatch_guards import _maybe_build_application_layer_reminder as reminder

APPROVAL_QUESTION = "qui approuve les congés dans l'ERP ?"
DISTINCTION_QUESTION = "qu'est-ce qui distingue réellement un acheteur d'un responsable ?"
DATA_QUESTION = "combien de congés validés ce mois-ci ?"


class ApplicationLayerReminderTests(unittest.TestCase):
    def test_approval_question_with_workflow_only_gets_reminder(self):
        self.assertIn("read_source_code", reminder(APPROVAL_QUESTION, ["describe_workflow"]))

    def test_approval_question_after_guard_read_gets_no_reminder(self):
        self.assertIsNone(reminder(APPROVAL_QUESTION, ["describe_workflow", "read_source_code"]))

    def test_approval_question_without_structure_observation_gets_no_reminder(self):
        self.assertIsNone(reminder(APPROVAL_QUESTION, []))
        self.assertIsNone(reminder(APPROVAL_QUESTION, ["orm_search_read"]))

    def test_data_question_with_orm_tools_gets_no_reminder(self):
        self.assertIsNone(reminder(DATA_QUESTION, ["orm_search_read"]))

    def test_distinction_reminder_is_unchanged(self):
        self.assertIn("distinction", reminder(DISTINCTION_QUESTION, ["who_has_access_to"]))
        self.assertIsNone(reminder(DISTINCTION_QUESTION, ["describe_workflow"]))
        self.assertIsNone(reminder(DISTINCTION_QUESTION, ["who_has_access_to", "read_source_code"]))


if __name__ == "__main__":
    unittest.main()
