"""
Diagnostic ponctuel -- todo/contexte.txt section 292/293/299/300 (Bug C,
piste i).

Lit les scores de similarite cosine BRUTS renvoyes par vector_search() seul
(sans RRF, sans candidate_count=200, sans reranker) pour un ensemble de
questions -- hors-sujet/salutations, acquiescements courts (nouveaux,
section 299 -- "d'accord" a fait ressortir un trou), et une question
metier pertinente en controle -- afin de recalibrer empiriquement le
plancher min_similarity avec un echantillon plus large que les 3 requetes
d'origine (section 293), plutot que de patcher a l'aveugle sur un seul cas.

Appelle vector_search() avec min_similarity=0.0 EXPLICITEMENT pour
contourner le plancher deja en place (config/settings.py) et voir la
distribution BRUTE complete, pas seulement ce qui passe deja le filtre
actuel -- sinon ce diagnostic ne montrerait plus rien d'utile depuis que
le plancher 0.20 existe par defaut.

Lecture seule : aucune ecriture dans ChromaDB, aucune modification de code
de production. A lancer sur le poste utilisateur (venv actif), coller la
sortie complete pour lecture.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from document_rag.vectorstore.search import get_retriever, vector_search, bm25_search

QUERIES = [
    # Salutations pures (deja calibrees en section 293, gardees ici comme
    # points de reference/non-regression pour situer le nouvel echantillon)
    "Bonjour",
    "Hello",
    # Acquiescements courts -- NOUVEAU (section 299), jamais testes lors
    # de la calibration d'origine, categorie qui a revele le trou
    "d'accord",
    "ok",
    "Ok",
    "compris",
    "entendu",
    "ça marche",
    "très bien",
    "parfait",
    # Question metier pertinente (deja calibree en section 293, controle
    # positif -- doit rester nettement au-dessus du bruit)
    "Comment créer une facture ?",
]

TOP_K = 15


def main() -> None:
    chroma_managers, bm25_index = get_retriever()

    for query in QUERIES:
        print(f"\n{'=' * 80}")
        print(f"QUERY: {query!r}")
        print(f"{'=' * 80}")

        # BM25 d'abord -- section 300 a montre que BM25=0 pour "Hello"/
        # "Bonjour"/"d'accord", hypothese a verifier sur le reste de
        # l'echantillon avant de decider si une corroboration BM25
        # (au lieu du seul plancher vectoriel) separe mieux les deux
        # classes.
        bm25_results = bm25_search(bm25_index, query, top_k=5)
        print(f"  BM25: {len(bm25_results)} resultat(s)")
        for r in bm25_results[:3]:
            metadata = r.get("metadata") or {}
            print(f"    bm25_score={r.get('score'):.4f}  source={metadata.get('source', 'unknown')}")

        # min_similarity=0.0 explicite : on veut la distribution BRUTE,
        # pas ce qui passe deja le plancher de production (0.20 par
        # defaut) -- sinon ce diagnostic serait aveugle a tout score sous
        # le seuil actuel, exactement ce qu'on a besoin de voir ici.
        results = vector_search(chroma_managers, query, top_k=TOP_K, min_similarity=0.0)

        if not results:
            print("  (aucun resultat vectoriel)")
            continue

        for rank, r in enumerate(results, start=1):
            metadata = r.get("metadata") or {}
            source = metadata.get("source", "unknown")
            doc_type = metadata.get("type", "unknown")
            similarity = r.get("score")
            print(
                f"  #{rank:2d}  similarity={similarity:.4f}  "
                f"type={doc_type:12s}  source={source}"
            )


if __name__ == "__main__":
    main()
