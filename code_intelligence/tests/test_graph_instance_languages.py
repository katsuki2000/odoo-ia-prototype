from code_intelligence.graph.loader import _merge_requested_languages


def test_active_instance_languages_are_requested_without_configuration():
    assert _merge_requested_languages(None, None, configured=["en_US", "fr_FR"]) == ("en_US", "fr_FR")


def test_request_language_is_added_to_the_instance_languages():
    assert _merge_requested_languages(["fr"], "de-DE", configured=["en_US"]) == ("de_DE", "en_US", "fr")
