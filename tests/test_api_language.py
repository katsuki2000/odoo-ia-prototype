import pytest

from api.language import request_language


@pytest.mark.parametrize('explicit, accept_language, expected', [
    ('fr-CA', 'en', 'fr_CA'),
    (None, 'en;q=0.5, fr;q=0.9', 'fr'),
    (None, 'en, fr', 'en'),
    (None, 'de;q=0, en;q=0.1', 'en'),
    ('not a tag!', 'es', 'es'),
    (None, None, None),
    (None, '*', None),
])
def test_request_language(explicit, accept_language, expected):
    assert request_language(explicit, accept_language) == expected
