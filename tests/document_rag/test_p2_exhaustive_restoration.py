"""Tests for P2 exhaustive restoration: contiguous expansion, dynamic budget, and completeness check."""


from config.settings import DOCUMENT_MAX_TOKENS
from document_rag.prompts import DOCUMENTARY_RAG_SYSTEM_PROMPT
from document_rag.verification import verify_documentary_completeness
from document_rag.vectorstore.search_contiguous import (
    contains_list_or_table,
    expand_contiguous_chunks,
)


def test_contains_list_or_table():
    assert contains_list_or_table("- Item one\n- Item two") is True
    assert contains_list_or_table("1. Step one\n2. Step two") is True
    assert contains_list_or_table("| Col A | Col B |\n| --- | --- |") is True
    assert contains_list_or_table("Ceci est un texte continu en prose sans aucune liste.") is False


def test_expand_contiguous_chunks_skips_plain_text():
    chunks = [
        {"document": "Texte simple sans liste.", "metadata": {"source": "doc1.txt", "chunk_index": 0, "total_chunks": 2}},
    ]
    expanded = expand_contiguous_chunks(chunks, chroma_manager=None)
    assert len(expanded) == 1
    assert expanded[0]["document"] == chunks[0]["document"]


def test_expand_contiguous_chunks_pulls_adjacent_chunks():
    class FakeCollection:
        def get(self, where=None):
            return {
                "ids": ["doc1_0", "doc1_1", "doc1_2"],
                "documents": [
                    "Introduction au guide.",
                    "- Premiere regle\n- Deuxieme regle",
                    "- Troisieme regle\n- Conclusion",
                ],
                "metadatas": [
                    {"source": "doc1.txt", "chunk_index": 0, "total_chunks": 3},
                    {"source": "doc1.txt", "chunk_index": 1, "total_chunks": 3},
                    {"source": "doc1.txt", "chunk_index": 2, "total_chunks": 3},
                ],
            }

    class FakeChromaManager:
        collection = FakeCollection()

    # Initial search only returned chunk 1 (the middle list chunk)
    initial_chunks = [
        {
            "id": "doc1_1",
            "document": "- Premiere regle\n- Deuxieme regle",
            "metadata": {"source": "doc1.txt", "chunk_index": 1, "total_chunks": 3},
        }
    ]

    expanded = expand_contiguous_chunks(initial_chunks, chroma_manager=FakeChromaManager())
    # Should pull chunk 0 and chunk 2, ordered by chunk_index
    assert len(expanded) == 3
    indices = [c["metadata"]["chunk_index"] for c in expanded]
    assert indices == [0, 1, 2]
    assert expanded[0]["is_contiguous_expansion"] is True
    assert expanded[2]["is_contiguous_expansion"] is True


def test_verify_documentary_completeness_exhaustive():
    chunks = [
        {
            "document": "## Procédure de validation\n- Créer la commande\n- Vérifier les stocks\n- Valider le paiement",
            "metadata": {"source": "procedure.md"},
        }
    ]
    answer = (
        "Voici la procédure complète :\n"
        "1. Créer la commande\n"
        "2. Vérifier les stocks\n"
        "3. Valider le paiement"
    )
    report = verify_documentary_completeness(answer, chunks)
    assert report.is_exhaustive is True
    assert report.recall == 1.0
    assert report.total_expected_items == 3
    assert report.restituted_items == 3
    assert report.missing_items == []


def test_verify_documentary_completeness_omission_detected():
    chunks = [
        {
            "document": "## Critères de conformité\n- Facture acquittée\n- Bon de livraison signé\n- Relevé bancaire joint",
            "metadata": {"source": "criteres.md"},
        }
    ]
    # Answer only mentions invoice and bank statement, omits delivery slip
    answer = "Les critères nécessaires sont la facture acquittée et le relevé bancaire joint."
    report = verify_documentary_completeness(answer, chunks)
    assert report.is_exhaustive is False
    assert report.total_expected_items == 3
    assert report.restituted_items == 2
    assert len(report.missing_items) == 1
    assert "Bon de livraison signé" in report.missing_items[0]


def test_documentary_prompt_rule_enforces_exhaustive_restitution():
    assert "Restitution exhaustive" in DOCUMENTARY_RAG_SYSTEM_PROMPT
    assert "sans en omettre aucun" in DOCUMENTARY_RAG_SYSTEM_PROMPT


def test_document_max_tokens_setting_is_configured():
    assert DOCUMENT_MAX_TOKENS >= 1024
