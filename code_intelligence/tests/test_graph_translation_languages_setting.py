from code_intelligence.graph.loader import _merge_requested_languages


def test_configured_requested_and_request_languages_are_merged_and_normalized():
    merged = _merge_requested_languages(["fr"], "en-US", configured=("fr_FR", " "))
    assert merged == ("en_US", "fr", "fr_FR")


def test_nothing_requested_gives_an_empty_set():
    assert _merge_requested_languages(None, None) == ()
