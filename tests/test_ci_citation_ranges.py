"""Offline regressions for citation provenance ranges."""

import importlib.util
from pathlib import Path
import sys
import unittest

modulePath = Path(__file__).resolve().parents[1] / 'code_intelligence/agent/source_boundary.py'
spec = importlib.util.spec_from_file_location('ci_citation_ranges_boundary', modulePath)
boundary = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = boundary
spec.loader.exec_module(boundary)


class CitationRangeTests(unittest.TestCase):
    def render(self, answerRange, observationRange, lineNumber=10):
        path = 'file:///addons/demo.py'
        answer = f'[source]({path}#{answerRange})\n\n```python\nself.check_access()\n```'
        observation = f'[source]({path}#{observationRange})\n{lineNumber} | self.check_access()'
        return boundary.enforce_source_blocks(answer, [observation])

    def test_zero_line_cannot_be_evidence(self):
        self.assertNotIn('self.check_access()', self.render('L0-L0', 'L0-L0', 0))

    def test_zero_start_observation_is_not_provenance(self):
        self.assertNotIn('self.check_access()', self.render('L10-L10', 'L0-L10'))

    def test_zero_start_answer_citation_is_not_provenance(self):
        self.assertNotIn('self.check_access()', self.render('L0-L10', 'L10-L10'))

    def test_reversed_observation_is_rejected(self):
        self.assertNotIn('self.check_access()', self.render('L10-L10', 'L12-L10'))

    def test_reversed_answer_range_is_rejected(self):
        self.assertNotIn('self.check_access()', self.render('L12-L10', 'L10-L12'))

    def test_valid_subset_is_preserved(self):
        self.assertIn('self.check_access()', self.render('L10-L10', 'L1-L20'))

    def test_oversized_numbered_line_fails_closed(self):
        self.assertNotIn('self.check_access()', self.render('L10-L10', 'L10-L10', '9' * 5000))

    def test_oversized_decimal_bound_fails_closed(self):
        oversizedRange = f"L{'9' * 5000}-L10"
        self.assertNotIn('self.check_access()', self.render('L10-L10', oversizedRange))


if __name__ == '__main__':
    unittest.main()
