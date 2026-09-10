"""
Tests for document_rag/generate_node.py -- _build_source_aliases() et
_verify_used_sources().

Section 336 (todo/contexte.txt) : le LLM ne voit plus jamais l'id ChromaDB
brut (chemin absolu + hash) mais un alias court propre au tour (S1, S2,
...). Couvre :
1. used_sources valide -> seules les sources correspondantes apparaissent
2. used_sources partiellement invalide -> seules les valides apparaissent + warning
3. used_sources entierement invalide -> sources=[] + fallback historique
4. aucun used_sources -> fallback historique
5. plusieurs chunks du meme fichier -> deduplique en une seule
   SourceReference (source, title) -- section 391/392, remplace l'ancien
   contrat "identite du chunk conservee" de la section 329
6. les alias sont strictement locaux au tour -- aucun etat partage entre
   deux appels de _build_source_aliases()
7. cas limites explicites (S1 valide / S99 inexistant / combinaison des deux)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from document_rag.generate_node import _build_source_aliases, _verify_used_sources
from core.schemas import SourceReference


def _make_chunk(chunk_id, source="wiki_approbation.txt", document="Contenu de test"):
    return {
        "id": chunk_id,
        "document": document,
        "metadata": {"source": source, "type": "wiki", "title": source},
    }


class TestBuildSourceAliases(unittest.TestCase):
    """L'alias map est construite localement, jamais un etat partage."""

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
        """Deux appels successifs avec des chunks differents ne doivent
        jamais laisser un alias d'un tour pointer vers le chunk d'un
        autre tour -- pas de cache/etat module-level."""
        chunks_turn_1 = [_make_chunk("x_0", source="x.txt")]
        chunks_turn_2 = [_make_chunk("y_0", source="y.txt"), _make_chunk("z_0", source="z.txt")]

        alias_map_1 = _build_source_aliases(chunks_turn_1)
        alias_map_2 = _build_source_aliases(chunks_turn_2)

        self.assertEqual(alias_map_1["S1"]["metadata"]["source"], "x.txt")
        self.assertEqual(alias_map_2["S1"]["metadata"]["source"], "y.txt")
        self.assertEqual(alias_map_2["S2"]["metadata"]["source"], "z.txt")
        # L'ancien alias_map_1 reste inchange -- pas de mutation partagee.
        self.assertEqual(alias_map_1["S1"]["metadata"]["source"], "x.txt")

    def test_raw_chunk_id_never_becomes_the_alias(self):
        """L'alias ne doit jamais etre (ou contenir) l'id ChromaDB brut --
        c'est precisement ce que ce chantier evite d'exposer au LLM."""
        long_chunk_id = "/media/donnee/projets/odoo-ia-prototype/document_rag/fake_data/documents/Miro - SMA, MMT.md_4_8bb42c1ef205"
        chunks = [_make_chunk(long_chunk_id, source="Miro - SMA, MMT.md")]
        alias_map = _build_source_aliases(chunks)
        self.assertEqual(list(alias_map.keys()), ["S1"])
        self.assertNotIn(long_chunk_id, alias_map.keys())


class TestVerifyUsedSources(unittest.TestCase):
    """1. used_sources valide -> seules les sources correspondantes apparaissent."""

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
        # LLM cite dans l'ordre inverse -- la sortie doit suivre l'ordre de recuperation.
        result = _verify_used_sources(["S2", "S1"], alias_map)

        self.assertEqual([r.source for r in result], ["a.txt", "b.txt"])


class TestPartiallyInvalidUsedSources(unittest.TestCase):
    """2. used_sources partiellement invalide -> seules les valides apparaissent + warning."""

    def test_partial_invalid_alias_keeps_only_valid_and_warns(self):
        chunks = [
            _make_chunk("a_0", source="wiki_a.txt"),
            _make_chunk("b_0", source="wiki_b.txt"),
        ]
        alias_map = _build_source_aliases(chunks)
        with self.assertLogs("document_rag.generate_helpers", level="WARNING") as cm:
            result = _verify_used_sources(["S1", "S99"], alias_map)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].source, "wiki_a.txt")
        self.assertTrue(any("invalid_used_sources" in msg for msg in cm.output))
        self.assertTrue(any("S99" in msg for msg in cm.output))


class TestFullyInvalidUsedSources(unittest.TestCase):
    """3. used_sources entierement invalide -> sources=[] + fallback historique."""

    def test_all_invalid_aliases_return_empty_and_warn(self):
        chunks = [_make_chunk("a_0", source="wiki_a.txt")]
        alias_map = _build_source_aliases(chunks)
        with self.assertLogs("document_rag.generate_helpers", level="WARNING") as cm:
            result = _verify_used_sources(["S99", "S100"], alias_map)

        self.assertEqual(result, [])
        self.assertTrue(any("invalid_used_sources" in msg for msg in cm.output))

    def test_s99_nonexistent_reproduces_real_incident_shape(self):
        """Cas limite explicite discute avec l'utilisateur : S1 valide,
        S99 inexistant, ['S1','S99'] doit garder S1 -- pendant que
        ['S99'] seul (aucun alias valide) doit retomber sur []."""
        chunks = [_make_chunk("a_0", source="wiki_a.txt")]
        alias_map = _build_source_aliases(chunks)

        with self.assertLogs("document_rag.generate_helpers", level="WARNING"):
            mixed = _verify_used_sources(["S1", "S99"], alias_map)
        self.assertEqual(len(mixed), 1)

        with self.assertLogs("document_rag.generate_helpers", level="WARNING"):
            only_invalid = _verify_used_sources(["S99"], alias_map)
        self.assertEqual(only_invalid, [])


class TestNoUsedSources(unittest.TestCase):
    """4. aucun used_sources -> fallback historique."""

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
    """5. plusieurs chunks du meme fichier -> deduplique par (source, title)
    en une seule SourceReference (section 391/392, todo/contexte.txt).
    Cette classe verrouillait a l'origine (section 329) le contrat inverse
    ("identite du chunk conservee, pas seulement le nom du fichier") --
    contrat depuis explicitement remplace par la dedup (cf. section 391/392
    et TestVerifyUsedSourcesDedup dans tests/test_graph.py, qui couvre deja
    ce mecanisme sur un autre fixture). Le test ci-dessous reprend le cas
    concret original (asset_loan.py cite deux fois via des alias differents,
    S3/S7 dans un contexte a 10 chunks) mais verrouille desormais le
    comportement actuel plutot que celui, perime, qu'il verrouillait."""

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

        # Meme (source, title) -> deduplique a 1 SourceReference ; premiere
        # occurrence (ordre de recuperation, S3) l'emporte, S7 est ecarte.
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
