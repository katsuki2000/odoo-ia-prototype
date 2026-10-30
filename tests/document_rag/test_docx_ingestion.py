import pytest

docx = pytest.importorskip("docx")

from document_rag.ingestion import ingest_handlers_doc
from document_rag.ingestion.docx_reader import docx_to_markdown
from document_rag.ingestion.file_formats import is_supported_document
from document_rag.ingestion.incremental import _scan_supported_files
from document_rag.ingestion.wiki_loader import WikiLoader, load_wiki_directory


def set_list_level(paragraph, level):
    paragraph._p.get_or_add_pPr().get_or_add_numPr().get_or_add_ilvl().val = level


def build_document(path):
    document = docx.Document()
    document.add_heading("Guide interne", level=1)
    document.add_paragraph("Introduction du guide.")
    document.add_heading("Sauvegardes", level=2)
    document.add_paragraph("Sauvegarde complete quotidienne", style="List Bullet")
    nested = document.add_paragraph("Conservee sur un disque separe", style="List Bullet")
    set_list_level(nested, 1)
    document.add_paragraph("Retention de 30 jours", style="List Bullet")
    table = document.add_table(rows=3, cols=2)
    table.cell(0, 0).text = "Niveau"
    table.cell(0, 1).text = "Delai"
    table.cell(1, 0).text = "Critique"
    table.cell(1, 1).text = "1h"
    table.cell(2, 0).merge(table.cell(2, 1)).text = "Autres niveaux"
    document.save(str(path))
    return path


@pytest.fixture
def docs_dir(tmp_path):
    build_document(tmp_path / "plan.docx")
    (tmp_path / "~$plan.docx").write_bytes(b"lock")
    (tmp_path / "notes.txt").write_text("Notes\n\n- a\n- b\n", encoding="utf-8")
    return tmp_path


def test_docx_to_markdown_keeps_structure_and_order(tmp_path):
    lines = docx_to_markdown(build_document(tmp_path / "plan.docx")).splitlines()
    assert lines[0] == "# Guide interne"
    assert "## Sauvegardes" in lines
    assert "- Sauvegarde complete quotidienne" in lines
    assert "  - Conservee sur un disque separe" in lines
    assert lines.index("## Sauvegardes") < lines.index("| Niveau | Delai |")
    assert "| Critique | 1h |" in lines
    assert "| Autres niveaux |" in lines


def test_load_docx_file_builds_chunks_with_relative_source(docs_dir):
    result = WikiLoader(chunk_size=200, chunk_overlap=20).load_docx_file(docs_dir / "plan.docx", scan_root=docs_dir)
    assert result["chunks"]
    assert {metadata["source"] for metadata in result["metadatas"]} == {"plan.docx"}
    assert {metadata["title"] for metadata in result["metadatas"]} == {"Guide interne"}
    assert all(metadata["type"] == "doc_wiki" for metadata in result["metadatas"])


def test_load_docx_file_rejects_other_extensions(docs_dir):
    with pytest.raises(ValueError):
        WikiLoader().load_docx_file(docs_dir / "notes.txt")


def test_format_predicates_ignore_office_lock_files():
    assert is_supported_document("plan.docx")
    assert is_supported_document("scan.PDF")
    assert not is_supported_document("~$plan.docx")
    assert not is_supported_document("data.csv")


def test_incremental_scan_includes_docx_and_skips_lock_files(docs_dir):
    names = sorted(path.name for path in _scan_supported_files([docs_dir]))
    assert names == ["notes.txt", "plan.docx"]


def test_ingest_documents_dir_indexes_docx_and_skips_lock_files(docs_dir):
    class Manager:
        def add_chunks(self, chunks, metadatas):
            return list(range(len(chunks)))

    stats = {"total_chunks": 0, "by_source": {}, "by_type": {}, "load_times": {}}
    ingest_handlers_doc.ingest_documents_dir(docs_dir, Manager(), stats, chunk_size=200, chunk_overlap=20)
    assert sorted(stats["by_source"]) == ["notes.txt", "plan.docx"]
    assert stats["by_type"]["doc_wiki"] == stats["total_chunks"]


def test_wiki_directory_loader_includes_docx_and_skips_office_lock_files(docs_dir):
    documents = load_wiki_directory(docs_dir, chunk_size=200, chunk_overlap=20, scan_root=docs_dir)
    sources = {
        metadata["source"]
        for document in documents
        for metadata in document["metadatas"]
    }
    assert sources == {"notes.txt", "plan.docx"}
