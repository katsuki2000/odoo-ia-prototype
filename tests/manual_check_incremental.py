"""
Test de validation de la réindexation incrémentale (Sprint 6).

Couvre :
1. Modification d'un fichier doc (odoo_docs) — wiki_approbation.txt
2. Modification d'un fichier code (odoo_code) — stock/barcode.py
3. Ajout d'un nouveau fichier
4. Suppression d'un fichier existant

Pour chaque cas : vérifie que seuls les chunks concernés sont régénérés,
sans affecter les autres sources.

Usage :
    python miro-rag/tests/test_incremental.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from document_rag.ingestion.incremental import reindex_if_changed
from document_rag.vectorstore.chroma_manager import ChromaManager

DOCS_DIR = PROJECT_ROOT / "document_rag/fake_data" / "documents"
CODE_DIR = Path("/home/user/odoo-17.0/addons") if Path("/home/user/odoo-17.0/addons").exists() else PROJECT_ROOT.parent / "addons"

# Fichiers cibles
DOC_TARGET = DOCS_DIR / "wiki_approbation.txt"
CODE_TARGET = CODE_DIR / "stock" / "models" / "barcode.py"
NEW_FILE = CODE_DIR / "stock" / "models" / "_test_temp_new_file.py"
DELETE_TARGET_SOURCE = CODE_DIR / "stock" / "models" / "res_users.py"  # court, 1 chunk


def get_hashes(manager: ChromaManager, source: str) -> list[str]:
    results = manager.collection.get(
        where={"source": {"$eq": source}},
        include=["metadatas"],
    )
    return sorted(str(m.get("content_hash", "")) for m in results.get("metadatas", []))


def sync(docs_manager, code_manager):
    return reindex_if_changed(
        roots=[DOCS_DIR, CODE_DIR],
        docs_manager=docs_manager,
        code_manager=code_manager,
    )


def test_modification(manager, target_file: Path, label: str) -> bool:
    print(f"\n--- Test modification : {label} ({target_file.name}) ---")
    source_str = str(target_file.resolve())
    original = target_file.read_text(encoding="utf-8")
    backup = target_file.with_suffix(target_file.suffix + ".bak")
    shutil.copy(target_file, backup)

    docs_manager = ChromaManager(collection_name="odoo_docs")
    code_manager = ChromaManager(collection_name="odoo_code")

    try:
        sync(docs_manager, code_manager)  # référence
        hashes_before = get_hashes(manager, source_str)

        target_file.write_text(
            original + f"\n# TEST INCREMENTAL — ligne ajoutée ({label})\n",
            encoding="utf-8",
        )

        result = sync(docs_manager, code_manager)
        hashes_after = get_hashes(manager, source_str)

        ok = True
        if source_str in result["updated_files"]:
            print(f"    ✅ {target_file.name} détecté comme modifié")
        else:
            print(f"    ❌ {target_file.name} PAS détecté comme modifié")
            ok = False

        others = [f for f in result["updated_files"] if f != source_str]
        if not others:
            print("    ✅ Aucun autre fichier affecté")
        else:
            print(f"    ❌ Fichiers inattendus mis à jour : {others}")
            ok = False

        if hashes_before != hashes_after:
            print(f"    ✅ Hashes modifiés ({len(hashes_before)} → {len(hashes_after)} chunks)")
        else:
            print("    ❌ Hashes inchangés")
            ok = False

        return ok
    finally:
        shutil.copy(backup, target_file)
        backup.unlink()
        sync(docs_manager, code_manager)


def test_addition() -> bool:
    print(f"\n--- Test ajout : {NEW_FILE.name} ---")
    source_str = str(NEW_FILE.resolve())
    docs_manager = ChromaManager(collection_name="odoo_docs")
    code_manager = ChromaManager(collection_name="odoo_code")

    try:
        NEW_FILE.write_text(
            "# Fichier temporaire de test\nclass TestModel:\n    pass\n",
            encoding="utf-8",
        )
        result = sync(docs_manager, code_manager)

        ok = True
        if source_str in result["added_files"]:
            print(f"    ✅ {NEW_FILE.name} détecté comme nouveau fichier")
        else:
            print(f"    ❌ {NEW_FILE.name} PAS détecté comme ajouté")
            ok = False

        if result["chunks_added"] >= 1:
            print(f"    ✅ {result['chunks_added']} chunk(s) ajouté(s)")
        else:
            print("    ❌ Aucun chunk ajouté")
            ok = False

        return ok
    finally:
        if NEW_FILE.exists():
            NEW_FILE.unlink()
        sync(docs_manager, code_manager)  # nettoie les chunks orphelins de NEW_FILE


def test_deletion() -> bool:
    print(f"\n--- Test suppression : {DELETE_TARGET_SOURCE.name} ---")
    source_str = str(DELETE_TARGET_SOURCE.resolve())
    backup = DELETE_TARGET_SOURCE.with_suffix(".py.bak")
    original = DELETE_TARGET_SOURCE.read_text(encoding="utf-8")
    shutil.copy(DELETE_TARGET_SOURCE, backup)

    docs_manager = ChromaManager(collection_name="odoo_docs")
    code_manager = ChromaManager(collection_name="odoo_code")

    try:
        sync(docs_manager, code_manager)  # référence, fichier présent
        hashes_before = get_hashes(code_manager, source_str)

        DELETE_TARGET_SOURCE.unlink()
        result = sync(docs_manager, code_manager)

        ok = True
        if source_str in result["deleted_files"]:
            print(f"    ✅ {DELETE_TARGET_SOURCE.name} détecté comme supprimé")
        else:
            print(f"    ❌ {DELETE_TARGET_SOURCE.name} PAS détecté comme supprimé")
            ok = False

        hashes_after = get_hashes(code_manager, source_str)
        if hashes_before and not hashes_after:
            print(f"    ✅ Chunks retirés de ChromaDB ({len(hashes_before)} → 0)")
        else:
            print(f"    ❌ Chunks toujours présents ({len(hashes_after)})")
            ok = False

        return ok
    finally:
        DELETE_TARGET_SOURCE.write_text(original, encoding="utf-8")
        backup.unlink()
        sync(docs_manager, code_manager)  # ré-indexe le fichier restauré


def run_all() -> bool:
    print("=" * 60)
    print("TEST — Réindexation incrémentale (couverture complète)")
    print("=" * 60)

    results = {
        "modification (doc)": test_modification(
            ChromaManager(collection_name="odoo_docs"), DOC_TARGET, "doc"
        ),
        "modification (code)": test_modification(
            ChromaManager(collection_name="odoo_code"), CODE_TARGET, "code"
        ),
        "ajout": test_addition(),
        "suppression": test_deletion(),
    }

    print("\n" + "=" * 60)
    print("RÉSUMÉ")
    print("=" * 60)
    for name, passed in results.items():
        print(f"  {'✅' if passed else '❌'} {name}")

    return all(results.values())


if __name__ == "__main__":
    success = run_all()
    print("\n" + "=" * 60)
    print("RÉSULTAT GLOBAL : " + ("✅ TOUS LES TESTS RÉUSSIS" if success else "❌ AU MOINS UN TEST ÉCHOUÉ"))
    print("=" * 60)
    sys.exit(0 if success else 1)