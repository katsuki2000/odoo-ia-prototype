"""Offline regressions for authorized source rendering and source ranges."""

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

modulePath = Path(__file__).resolve().parents[1] / 'code_intelligence/agent/source_boundary.py'
spec = importlib.util.spec_from_file_location('ci_source_boundary', modulePath)
boundary = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = boundary
spec.loader.exec_module(boundary)


class SourceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.link = '[source](file:///addons/demo/models/item.py#L10-L12)'
        self.code = 'def confirm(self):\n    self.check_access()\n    return True'
        self.observation = f'Source: {self.link}\n  10 | def confirm(self):\n  11 |     self.check_access()\n  12 |     return True'
        self.answer = f'{self.link}\n\n```python\n{self.code}\n```'

    def render(self, answer=None, observations=None):
        return boundary.enforce_source_blocks(
            self.answer if answer is None else answer,
            [self.observation] if observations is None else observations,
        )

    def test_exact_authorized_source_is_preserved(self):
        self.assertIn(self.code, self.render())

    def test_fabricated_code_is_removed(self):
        self.assertNotIn('sudo()', self.render(self.answer.replace('check_access()', 'sudo()')))

    def test_no_evidence_means_no_code(self):
        self.assertNotIn('def confirm', self.render(observations=[]))

    def test_foreign_file_citation_is_rejected(self):
        self.assertNotIn('def confirm', self.render(self.answer.replace('item.py', 'secret.py')))

    def test_unobserved_lines_are_rejected(self):
        self.assertNotIn('def confirm', self.render(self.answer.replace('L10-L12', 'L1-L3')))

    def test_redacted_gap_cannot_be_reassembled(self):
        redacted = self.observation.replace('  11 |     self.check_access()', 'ELEMENT OMITTED FOR AUTHORIZATION REASON')
        self.assertNotIn('def confirm', self.render(observations=[redacted]))

    def test_separate_observations_cannot_be_reassembled(self):
        first = f'Source: {self.link}\n 10 | def confirm(self):'
        second = f'Source: {self.link}\n 11 |     self.check_access()\n 12 |     return True'
        self.assertNotIn('def confirm', self.render(observations=[first, second]))

    def test_multiple_source_paths_are_ambiguous(self):
        other = '[other](file:///addons/other.py#L10-L12)'
        self.assertNotIn('def confirm', self.render(observations=[self.observation + '\n' + other]))

    def test_rendering_never_reads_the_filesystem(self):
        with patch.object(Path, 'open', side_effect=AssertionError('Unexpected disk access')):
            self.assertIn(self.code, self.render())

    def test_numbered_blocks_are_normalized_from_evidence(self):
        numbered = '\n'.join(self.observation.splitlines()[1:])
        answer = f'{self.link}\n\n```\n{numbered}\n```'
        self.assertIn(self.code, self.render(answer))

    def test_long_backtick_fences_are_checked(self):
        answer = self.answer.replace('```', '````')
        self.assertNotIn('sudo()', self.render(answer.replace('check_access()', 'sudo()')))

    def test_tilde_fences_are_checked(self):
        answer = self.answer.replace('```', '~~~')
        self.assertNotIn('sudo()', self.render(answer.replace('check_access()', 'sudo()')))

    def test_code_subset_requires_its_own_valid_range(self):
        answer = '[source](file:///addons/demo/models/item.py#L11-L12)\n\n```\n    self.check_access()\n    return True\n```'
        self.assertIn('    self.check_access()', self.render(answer))

    def test_absent_source_citation_rejects_code(self):
        self.assertNotIn('def confirm', self.render(self.answer.replace(self.link, '')))

    def test_prose_is_unchanged(self):
        self.assertEqual(self.render('An explanation without a code block.'), 'An explanation without a code block.')

    def test_input_observations_are_not_mutated(self):
        observations = [self.observation]
        boundary.enforce_source_blocks(self.answer, observations)
        self.assertEqual(observations, [self.observation])


class SourceRangeTests(unittest.TestCase):
    def test_valid_ranges(self):
        for first, last, maximum in [(1, 1, 200), (1, 200, 200), (10, 20, 11)]:
            with self.subTest(first=first, last=last):
                self.assertIsNone(boundary.validate_source_range(first, last, maximum))

    def test_invalid_ranges(self):
        for first, last, maximum in [(1, -1, 200), (0, 20, 200), (-1, 20, 200), (20, 10, 200), (1, 201, 200), (1, 1, 0)]:
            with self.subTest(first=first, last=last, maximum=maximum):
                self.assertTrue(boundary.validate_source_range(first, last, maximum).startswith('Error:'))

    def test_non_integer_bounds_are_rejected(self):
        for first, last, maximum in [(True, 1, 200), (1, False, 200), ('1', 20, 200), (1, 20.0, 200), (1, 20, None)]:
            with self.subTest(first=first, last=last):
                self.assertTrue(boundary.validate_source_range(first, last, maximum).startswith('Error:'))


if __name__ == '__main__':
    unittest.main()
