"""Code rendering must use only authorized observations, never disk reads."""

from unittest.mock import patch

from code_intelligence.agent.dispatch_guards import substitute_or_strip_code_blocks
from code_intelligence.agent.tools.introspection import read_precise_source_code


LINK = '[item.py:L1-L2](file:///addons/demo/item.py#L1-L2)'
CODE = 'def confirm(self):\n    return True'
OBSERVATION = f'Source: {LINK}\n   1 | def confirm(self):\n   2 |     return True'


def test_authorized_exact_source_is_preserved():
    answer = f'{LINK}\n\n```python\n{CODE}\n```'
    with patch('code_intelligence.agent.tools.introspection.read_precise_source_code', side_effect=AssertionError('No disk reads allowed')):
        result = substitute_or_strip_code_blocks(answer, [OBSERVATION])
    assert CODE in result


def test_citation_alone_cannot_trigger_a_source_read():
    answer = f'{LINK}\n\n```python\n{CODE}\n```'
    result = substitute_or_strip_code_blocks(answer)
    assert CODE not in result
    assert 'bloc de code omis' in result


def test_fabricated_code_is_removed_even_with_a_valid_citation():
    answer = f'{LINK}\n\n```python\ndef confirm(self):\n    return self.sudo()\n```'
    result = substitute_or_strip_code_blocks(answer, [OBSERVATION])
    assert 'sudo()' not in result
    assert '```' not in result


def test_redacted_source_is_not_recovered():
    observation = f'Source: {LINK}\n   1 | def confirm(self):\nELEMENT OMITTED FOR AUTHORIZATION REASON'
    answer = f'{LINK}\n\n```python\n{CODE}\n```'
    result = substitute_or_strip_code_blocks(answer, [observation])
    assert CODE not in result


def test_source_cannot_be_joined_across_unobserved_lines():
    observation = f'Source: [item.py:L1-L3](file:///addons/demo/item.py#L1-L3)\n   1 | def confirm(self):\n   3 |     return True'
    answer = f'{LINK}\n\n```python\n{CODE}\n```'
    assert CODE not in substitute_or_strip_code_blocks(answer, [observation])


def test_prose_remains_unchanged():
    answer = 'The action has a Python-level check.'
    assert substitute_or_strip_code_blocks(answer, [OBSERVATION]) == answer


def test_invalid_source_range_is_rejected_before_filesystem_access():
    with patch('pathlib.Path.exists', side_effect=AssertionError('Bounds must be validated first')):
        for first, last in [(1, -1), (0, 20), (20, 10), (1, 201)]:
            assert read_precise_source_code('item.py', first, last).startswith('Error:')
