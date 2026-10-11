from code_intelligence.graph.loader import _merge_requested_languages


def test_configured_requested_and_request_languages_are_merged_and_normalized():
    merged = _merge_requested_languages(["fr"], "en-US", configured=("fr_FR", " "))
    assert merged == ("en_US", "fr", "fr_FR")


def test_nothing_requested_gives_an_empty_set():
    assert _merge_requested_languages(None, None) == ()


def test_interface_language_does_not_force_a_rebuild_when_its_catalog_is_present():
    from code_intelligence.graph.loader import _translation_cache_matches

    assert _translation_cache_matches(("fr_FR",), ("fr",))
    assert _translation_cache_matches(("en_US",), ())
    assert _translation_cache_matches(("fr",), ("fr",))
    assert not _translation_cache_matches(("de_DE",), ("fr",))
