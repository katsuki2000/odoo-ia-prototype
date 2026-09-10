"""
tests/test_confidence_tags.py

Unit tests for core/confidence_tags.py -- single source of truth for the
French confidence-level word used inside "[Confiance: ...]" tags (schema C,
cf. todo/contexte.txt Section 626).
"""

import pytest

from core.output.confidence_tags import confidence_label


class TestConfidenceLabel:
    def test_high_maps_to_elevee(self):
        assert confidence_label("high") == "ÉLEVÉE"

    def test_medium_maps_to_moyenne(self):
        assert confidence_label("medium") == "MOYENNE"

    def test_low_maps_to_faible(self):
        assert confidence_label("low") == "FAIBLE"

    def test_case_insensitive(self):
        assert confidence_label("HIGH") == "ÉLEVÉE"
        assert confidence_label("Low") == "FAIBLE"

    def test_unknown_level_raises_value_error(self):
        with pytest.raises(ValueError):
            confidence_label("bogus")

    def test_all_three_labels_are_distinct(self):
        labels = {confidence_label(l) for l in ("high", "medium", "low")}
        assert len(labels) == 3

    def test_all_labels_are_french_only_no_english_leak(self):
        for level in ("high", "medium", "low"):
            label = confidence_label(level)
            assert label not in ("HIGH", "MEDIUM", "LOW")
