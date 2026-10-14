"""Offline regressions for fenced-source boundary bypasses."""

import importlib.util
from pathlib import Path
import sys
import unittest

modulePath = Path(__file__).resolve().parents[1] / 'code_intelligence/agent/source_boundary.py'
spec = importlib.util.spec_from_file_location('ci_fenced_source_boundary', modulePath)
boundary = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = boundary
spec.loader.exec_module(boundary)


class SourceFenceTests(unittest.TestCase):
    def setUp(self):
        self.link = '[source](file:///addons/demo.py#L10-L11)'
        self.code = 'def confirm(self):\n    self.check_access()'
        self.observation = f'{self.link}\n10 | def confirm(self):\n11 |     self.check_access()'

    def render(self, block, observations=None):
        return boundary.enforce_source_blocks(self.link + '\n\n' + block, [self.observation] if observations is None else observations)

    def test_indented_fabrication_is_removed(self):
        for indent in (' ', '  ', '   ', '    ', '\t'):
            with self.subTest(indent=repr(indent)):
                self.assertNotIn('self.sudo()', self.render(f'{indent}```python\n{indent}self.sudo()\n{indent}```'))

    def test_authorized_indented_top_level_source_is_preserved(self):
        for indent in (' ', '  ', '   '):
            with self.subTest(indent=repr(indent)):
                code = '\n'.join(indent + line for line in self.code.splitlines())
                self.assertIn(self.code, self.render(f'{indent}```python\n{code}\n{indent}```'))

    def test_container_fences_fail_closed(self):
        for prefix in ('> ', '> > ', '- ', '* ', '+ ', '1. ', '2) ', '  - > '):
            with self.subTest(prefix=prefix):
                self.assertNotIn('self.sudo()', self.render(f'{prefix}```python\n{prefix}self.sudo()\n{prefix}```'))

    def test_unclosed_fabrication_is_removed(self):
        self.assertNotIn('self.sudo()', self.render('```python\nself.sudo()'))

    def test_unclosed_authorized_source_is_not_auto_completed(self):
        self.assertNotIn('def confirm', self.render(f'```python\n{self.code}'))

    def test_longer_closing_fence_is_checked(self):
        self.assertNotIn('self.sudo()', self.render('```python\nself.sudo()\n````'))

    def test_longer_closing_fence_preserves_authorized_source(self):
        self.assertIn(self.code, self.render(f'```python\n{self.code}\n````'))

    def test_tilde_fence_with_longer_closer_is_checked(self):
        self.assertNotIn('self.sudo()', self.render('~~~python\nself.sudo()\n~~~~'))

    def test_shorter_fence_inside_long_block_is_not_a_closer(self):
        self.assertNotIn('self.sudo()', self.render('````python\n```\nself.sudo()\n````'))

    def test_mismatched_closer_does_not_authorize_a_block(self):
        self.assertNotIn('self.sudo()', self.render('```python\nself.sudo()\n~~~'))

    def test_crlf_fabrication_is_removed(self):
        self.assertNotIn('self.sudo()', self.render('```python\r\nself.sudo()\r\n```\r\n'))

    def test_closed_block_preserves_following_prose(self):
        result = self.render('```python\nself.sudo()\n````\n\nFollowing explanation.')
        self.assertNotIn('self.sudo()', result)
        self.assertTrue(result.endswith('Following explanation.'))

    def test_adjacent_blocks_are_checked_independently(self):
        result = self.render(f'```python\nself.sudo()\n````\n\n```python\n{self.code}\n```')
        self.assertNotIn('self.sudo()', result)
        self.assertIn(self.code, result)

    def test_bare_unclosed_opener_is_removed(self):
        self.assertNotIn('```', self.render('```python'))


if __name__ == '__main__':
    unittest.main()
