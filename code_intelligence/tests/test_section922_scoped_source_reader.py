"""
code_intelligence/tests/test_section922_scoped_source_reader.py

Tests for Section 922:
1. read_precise_source_code resolves bare filenames to native/custom addons,
   never to tests/ fixture directories.
2. _GRAPH_REF priority resolution for model stems.
3. _PROSE_LINE_CLAIM_PATTERN properly recognizes unicode non-breaking hyphens (U+2011).
"""

import re
from pathlib import Path
import pytest

from code_intelligence.agent.dispatch_guards import _PROSE_LINE_CLAIM_PATTERN
from code_intelligence.agent.tools.introspection import read_precise_source_code
import code_intelligence.agent.tool_helpers as th


class TestProseLineClaimUnicodeDashes:
    def test_ascii_hyphen_range(self):
        text = "`purchase.order` (lignes 18-98)"
        m = _PROSE_LINE_CLAIM_PATTERN.search(text)
        assert m is not None
        assert m.group(1) == "purchase.order"
        assert m.group(2) == "18"
        assert m.group(3) == "98"

    def test_unicode_non_breaking_hyphen_range(self):
        # U+2011 (non-breaking hyphen)
        text = "`purchase.order` est créé dans le fichier **purchase_order.py** (ligne 18\u201198)"
        m = _PROSE_LINE_CLAIM_PATTERN.search(text)
        assert m is not None
        assert m.group(1) == "purchase.order"
        assert m.group(2) == "18"
        assert m.group(3) == "98"

    def test_en_dash_range(self):
        # U+2013 (en-dash)
        text = "`sale.order` (lignes 10\u201350)"
        m = _PROSE_LINE_CLAIM_PATTERN.search(text)
        assert m is not None
        assert m.group(2) == "10"
        assert m.group(3) == "50"


class TestScopedSourceReader:
    def test_bare_filename_resolves_to_native_not_tests(self):
        # res_company.py exists in both core addons and in tests/oca_sample/
        res = read_precise_source_code("res_company.py", 1, 20, include_citation=True)
        assert not res.startswith("Error")
        assert "tests/oca_sample" not in res
        assert "addons/" in res
