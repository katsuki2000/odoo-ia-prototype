"""Validate bounded source ranges before any file access."""

import pytest

from code_intelligence.agent.tools.source_boundary import validate_source_range


@pytest.mark.parametrize(
    ('first', 'last', 'maximum'),
    [(1, 1, 200), (1, 200, 200), (10, 20, 11)],
)
def test_valid_source_ranges(first, last, maximum):
    assert validate_source_range(first, last, maximum) is None


@pytest.mark.parametrize(
    ('first', 'last', 'maximum'),
    [
        (1, -1, 200), (0, 20, 200), (-1, 20, 200), (20, 10, 200),
        (1, 201, 200), (1, 1, 0), (True, 1, 200), (1, 20, None),
    ],
)
def test_invalid_source_ranges_are_rejected(first, last, maximum):
    assert validate_source_range(first, last, maximum).startswith('Error:')
