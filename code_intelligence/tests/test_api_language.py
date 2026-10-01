from api.routes_ask import _request_language


def test_explicit_request_language_precedes_accept_language():
    assert _request_language("fr-CA", "en-US,en;q=0.8") == "fr_CA"


def test_accept_language_uses_highest_supported_quality():
    assert _request_language(None, "en-US;q=0.4,fr-CA;q=0.9") == "fr_CA"


def test_invalid_language_falls_back_to_accept_language():
    assert _request_language("../fr", "fr;q=0.8,en;q=0.4") == "fr"


def test_missing_language_remains_unknown():
    assert _request_language(None, None) is None
