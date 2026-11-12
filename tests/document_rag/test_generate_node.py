"""
Tests for document_rag/generation/generate_node.py: _build_source_aliases() and
_verify_used_sources().

The LLM never sees the raw ChromaDB id, only a short per-turn alias (S1, S2, ...).
Covered:
1. valid used_sources -> only the matching sources appear
2. partially invalid used_sources -> only the valid ones appear, with a warning
3. fully invalid used_sources -> sources=[] and a warning
4. no used_sources -> []
5. several chunks of the same file -> deduplicated to one SourceReference (source, title)
6. aliases are local to the turn: no state shared between two calls
7. edge cases (S1 valid / S99 unknown / both)
"""

import os
import sys
import unittest

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "document_rag"))

from document_rag.generation.generate_node import _build_source_aliases, _verify_used_sources
from core.schemas import SourceReference


def _make_chunk(chunk_id, source="wiki_approbation.txt", document="Test content"):
    return {
        "id": chunk_id,
        "document": document,
        "metadata": {"source": source, "type": "wiki", "title": source},
    }


class TestBuildSourceAliases(unittest.TestCase):
    """The alias map is built locally, never shared state."""

    def test_aliases_are_s1_indexed_in_order(self):
        chunks = [
            _make_chunk("a_0", source="a.txt"),
            _make_chunk("b_0", source="b.txt"),
            _make_chunk("c_0", source="c.txt"),
        ]
        alias_map = _build_source_aliases(chunks)
        self.assertEqual(list(alias_map.keys()), ["S1", "S2", "S3"])
        self.assertEqual(alias_map["S1"]["metadata"]["source"], "a.txt")
        self.assertEqual(alias_map["S3"]["metadata"]["source"], "c.txt")

    def test_aliases_never_leak_across_calls(self):
        """An alias from one turn never points to a chunk of another turn (no module-level cache)."""
        chunks_turn_1 = [_make_chunk("x_0", source="x.txt")]
        chunks_turn_2 = [_make_chunk("y_0", source="y.txt"), _make_chunk("z_0", source="z.txt")]

        alias_map_1 = _build_source_aliases(chunks_turn_1)
        alias_map_2 = _build_source_aliases(chunks_turn_2)

        self.assertEqual(alias_map_1["S1"]["metadata"]["source"], "x.txt")
        self.assertEqual(alias_map_2["S1"]["metadata"]["source"], "y.txt")
        self.assertEqual(alias_map_2["S2"]["metadata"]["source"], "z.txt")
        # The first alias map is unchanged by the second call.
        self.assertEqual(alias_map_1["S1"]["metadata"]["source"], "x.txt")

    def test_raw_chunk_id_never_becomes_the_alias(self):
        """The alias is never the raw ChromaDB id, which must not be exposed to the LLM."""
        long_chunk_id = "docs/Miro - SMA, MMT.md_4_8bb42c1ef205"
        chunks = [_make_chunk(long_chunk_id, source="Miro - SMA, MMT.md")]
        alias_map = _build_source_aliases(chunks)
        self.assertEqual(list(alias_map.keys()), ["S1"])
        self.assertNotIn(long_chunk_id, alias_map.keys())


class TestVerifyUsedSources(unittest.TestCase):
    """Valid used_sources: only the matching sources appear."""

    def test_valid_alias_returns_only_matching_chunk(self):
        chunks = [
            _make_chunk("a_0", source="wiki_a.txt"),
            _make_chunk("b_0", source="wiki_b.txt"),
            _make_chunk("c_0", source="code_c.py"),
        ]
        alias_map = _build_source_aliases(chunks)
        result = _verify_used_sources(["S1"], alias_map)

        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], SourceReference)
        self.assertEqual(result[0].source, "wiki_a.txt")

    def test_valid_aliases_preserve_retrieval_order_not_llm_order(self):
        chunks = [
            _make_chunk("a_0", source="a.txt"),
            _make_chunk("b_0", source="b.txt"),
        ]
        alias_map = _build_source_aliases(chunks)
        # The LLM cites in reverse order: the output follows retrieval order.
        result = _verify_used_sources(["S2", "S1"], alias_map)

        self.assertEqual([r.source for r in result], ["a.txt", "b.txt"])


class TestPartiallyInvalidUsedSources(unittest.TestCase):
    """Partially invalid used_sources: only the valid ones appear, with a warning."""

    def test_partial_invalid_alias_keeps_only_valid_and_warns(self):
        chunks = [
            _make_chunk("a_0", source="wiki_a.txt"),
            _make_chunk("b_0", source="wiki_b.txt"),
        ]
        alias_map = _build_source_aliases(chunks)
        with self.assertLogs("document_rag.generation.generate_helpers", level="WARNING") as cm:
            result = _verify_used_sources(["S1", "S99"], alias_map)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].source, "wiki_a.txt")
        self.assertTrue(any("invalid_used_sources" in msg for msg in cm.output))
        self.assertTrue(any("S99" in msg for msg in cm.output))


class TestFullyInvalidUsedSources(unittest.TestCase):
    """Fully invalid used_sources: sources=[] and a warning."""

    def test_all_invalid_aliases_return_empty_and_warn(self):
        chunks = [_make_chunk("a_0", source="wiki_a.txt")]
        alias_map = _build_source_aliases(chunks)
        with self.assertLogs("document_rag.generation.generate_helpers", level="WARNING") as cm:
            result = _verify_used_sources(["S99", "S100"], alias_map)

        self.assertEqual(result, [])
        self.assertTrue(any("invalid_used_sources" in msg for msg in cm.output))

    def test_s99_nonexistent_reproduces_real_incident_shape(self):
        """['S1', 'S99'] keeps S1, while ['S99'] alone (no valid alias) gives []."""
        chunks = [_make_chunk("a_0", source="wiki_a.txt")]
        alias_map = _build_source_aliases(chunks)

        with self.assertLogs("document_rag.generation.generate_helpers", level="WARNING"):
            mixed = _verify_used_sources(["S1", "S99"], alias_map)
        self.assertEqual(len(mixed), 1)

        with self.assertLogs("document_rag.generation.generate_helpers", level="WARNING"):
            only_invalid = _verify_used_sources(["S99"], alias_map)
        self.assertEqual(only_invalid, [])


class TestNoUsedSources(unittest.TestCase):
    """No used_sources: empty result, no warning."""

    def test_empty_list_returns_empty_no_warning(self):
        chunks = [_make_chunk("a_0")]
        alias_map = _build_source_aliases(chunks)
        result = _verify_used_sources([], alias_map)
        self.assertEqual(result, [])

    def test_none_like_falsy_input_returns_empty(self):
        chunks = [_make_chunk("a_0")]
        alias_map = _build_source_aliases(chunks)
        result = _verify_used_sources(None, alias_map)
        self.assertEqual(result, [])


class TestSameFileMultipleChunks(unittest.TestCase):
    """Several chunks of the same file are deduplicated by (source, title) to one SourceReference."""

    def test_two_aliases_of_the_same_file_dedup_to_one_source_first_wins(self):
        chunks = (
            [_make_chunk(f"filler_{i}", source=f"filler_{i}.txt") for i in range(2)]
            + [_make_chunk("asset_loan.py_3_hash1", source="asset_loan.py", document="chunk 4")]
            + [_make_chunk(f"filler_{i}", source=f"filler_{i}.txt") for i in range(3, 6)]
            + [_make_chunk("asset_loan.py_8_hash2", source="asset_loan.py", document="chunk 9")]
        )
        alias_map = _build_source_aliases(chunks)
        # asset_loan.py chunk 4 -> S3, asset_loan.py chunk 9 -> S7 (index 1-based).
        self.assertEqual(alias_map["S3"]["document"], "chunk 4")
        self.assertEqual(alias_map["S7"]["document"], "chunk 9")

        result = _verify_used_sources(["S3", "S7"], alias_map)

        # Same (source, title): one SourceReference, the first occurrence (S3) wins and S7 is dropped.
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].source, "asset_loan.py")
        self.assertEqual(result[0].snippet, "chunk 4")

    def test_only_one_alias_of_the_same_file_cited_excludes_the_other(self):
        chunks = [
            _make_chunk("asset_loan.py_3_hash1", source="asset_loan.py", document="chunk 4"),
            _make_chunk("asset_loan.py_8_hash2", source="asset_loan.py", document="chunk 9"),
        ]
        alias_map = _build_source_aliases(chunks)
        result = _verify_used_sources(["S2"], alias_map)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].snippet, "chunk 9")


if __name__ == "__main__":
    unittest.main()
