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


def test_graph_languages_come_from_settings_with_french_by_default():
    import os
    import subprocess
    import sys

    script = "from config.settings import GRAPH_TRANSLATION_LANGUAGES as g; print(','.join(g))"
    env = {key: value for key, value in os.environ.items() if key != "GRAPH_TRANSLATION_LANGUAGES"}
    default = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env, check=True)
    custom = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                            env={**env, "GRAPH_TRANSLATION_LANGUAGES": " de_DE , "}, check=True)
    assert default.stdout.strip().endswith("en_US,fr_FR")
    assert custom.stdout.strip().endswith("de_DE")
