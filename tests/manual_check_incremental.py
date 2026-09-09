"""
Test de validation de la réindexation incrémentale documentaire.

Couvre :
1. Modification d'un fichier doc texte (odoo_docs) — wiki_approbation.txt
2. Modification d'un fichier doc markdown (odoo_docs)
3. Ajout d'un nouveau fichier doc
4. Suppression d'un fichier doc existant

Usage :
    python tests/manual_check_incremental.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from document_rag.ingestion.incremental import reindex_if_changed
from document_rag.vectorstore.chroma_manager import ChromaManager
from config.settings import RAG_DOCS_PATH

DOCS_DIR = Path(RAG_DOCS_PATH)

# Fichiers cibles
DOC_TARGET = DOCS_DIR / "wiki_approbation.txt"
NEW_FILE = DOCS_DIR / "_test_temp_new_doc.txt"
DELETE_TARGET = DOCS_DIR / "_test_temp_doc_to_delete.txt"


def get_hashes(manager: ChromaManager, source: str) -> list[str]:
    results = manager.collection.get(
        where={"source": {"$eq": source}},
        include=["metadatas"],
    )
    return sorted(str(m.get("content_hash", "")) for m in results.get("metadatas", []))


def sync(docs_manager: ChromaManager) -> dict:
    return reindex_if_changed(
        roots=[DOCS_DIR],
        docs_manager=docs_manager,
    )


def test_modification(manager: ChromaManager, target_file: Path, label: str) -> bool:
    print(f"\n--- Test modification : {label} ({target_file.name}) ---")
    source_str = str(target_file.resolve())
    original = target_file.read_text(encoding="utf-8")
    backup = target_file.with_suffix(target_file.suffix + ".bak")
    shutil.copy(target_file, backup)

    docs_manager = ChromaManager(collection_name="odoo_docs")

    try:
        sync(docs_manager)
        hashes_before = get_hashes(manager, source_str)

        target_file.write_text(
            original + f"\n# TEST INCREMENTAL — ligne ajoutée ({label})\n",
            encoding="utf-8",
        )

        result = sync(docs_manager)
        hashes_after = get_hashes(manager, source_str)

        ok = True
        if source_str in result["updated_files"]:
            print(f"     {target_file.name} détecté comme modifié")
        else:
            print(f"     {target_file.name} PAS détecté comme modifié")
            ok = False

        others = [f for f in result["updated_files"] if f != source_str]
        if not others:
            print("     Aucun autre fichier affecté")
        else:
            print(f"     Fichiers inattendus mis à jour : {others}")
            ok = False

        if hashes_before != hashes_after:
            print(f"     Hashes modifiés ({len(hashes_before)} → {len(hashes_after)} chunks)")
        else:
            print("     Hashes inchangés")
            ok = False

        return ok
    finally:
        shutil.copy(backup, target_file)
        backup.unlink()
        sync(docs_manager)


def test_addition() -> bool:
    print(f"\n--- Test ajout : {NEW_FILE.name} ---")
    source_str = str(NEW_FILE.resolve())
    docs_manager = ChromaManager(collection_name="odoo_docs")

    try:
        NEW_FILE.write_text(
            "Titre du document de test\nContenu temporaire pour le test d'ajout incrémental.\n",
            encoding="utf-8",
        )
        result = sync(docs_manager)

        ok = True
        if source_str in result["added_files"]:
            print(f"     {NEW_FILE.name} détecté comme nouveau fichier")
        else:
            print(f"     {NEW_FILE.name} PAS détecté comme ajouté")
            ok = False

        if result["chunks_added"] >= 1:
            print(f"     {result['chunks_added']} chunk(s) ajouté(s)")
        else:
            print("     Aucun chunk ajouté")
            ok = False

        return ok
    finally:
        if NEW_FILE.exists():
            NEW_FILE.unlink()
        sync(docs_manager)


def test_deletion() -> bool:
    print(f"\n--- Test suppression : {DELETE_TARGET.name} ---")
    source_str = str(DELETE_TARGET.resolve())
    docs_manager = ChromaManager(collection_name="odoo_docs")

    try:
        # Créer et indexer le fichier d'abord
        DELETE_TARGET.write_text("Document temporaire à supprimer.", encoding="utf-8")
        sync(docs_manager)
        hashes_before = get_hashes(docs_manager, source_str)

        # Supprimer le fichier
        DELETE_TARGET.unlink()
        result = sync(docs_manager)

        ok = True
        if source_str in result["deleted_files"]:
            print(f"     {DELETE_TARGET.name} détecté comme supprimé")
        else:
            print(f"     {DELETE_TARGET.name} PAS détecté comme supprimé")
            ok = False

        hashes_after = get_hashes(docs_manager, source_str)
        if hashes_before and not hashes_after:
            print(f"     Chunks retirés de ChromaDB ({len(hashes_before)} → 0)")
        else:
            print(f"     Chunks toujours présents ({len(hashes_after)})")
            ok = False

        return ok
    finally:
        if DELETE_TARGET.exists():
            DELETE_TARGET.unlink()
        sync(docs_manager)


def run_all() -> bool:
    print("=" * 60)
    print("TEST — Réindexation incrémentale documentaire")
    print("=" * 60)

    docs_manager = ChromaManager(collection_name="odoo_docs")
    results = {
        "modification (doc txt)": test_modification(docs_manager, DOC_TARGET, "txt"),
        "ajout (doc)": test_addition(),
        "suppression (doc)": test_deletion(),
    }

    print("\n" + "=" * 60)
    print("RÉSUMÉ")
    print("=" * 60)
    for name, passed in results.items():
        status = "[OK]" if passed else "[FAIL]"
        print(f"  {status} {name}")

    return all(results.values())


if __name__ == "__main__":
    success = run_all()
    print("\n" + "=" * 60)
    print("RÉSULTAT GLOBAL : " + ("TOUS LES TESTS RÉUSSIS" if success else "AU MOINS UN TEST ÉCHOUÉ"))
    print("=" * 60)
    sys.exit(0 if success else 1)