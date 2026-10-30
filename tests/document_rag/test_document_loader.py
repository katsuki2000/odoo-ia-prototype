import pytest

from document_rag.ingestion.document_loader import load_document
from document_rag.ingestion.ingest_handlers_doc import ingest_documents_dir


class PdfLoader:
    def load_and_chunk(self, path, scan_root=None):
        return {"chunks": ["pdf"], "metadatas": [{"source": path.name}]}


class WikiLoader:
    def load_text_file(self, path, scan_root=None):
        return {"chunks": ["text"], "metadatas": [{"source": path.name}]}

    def load_markdown_file(self, path, scan_root=None):
        return {"chunks": ["markdown"], "metadatas": [{"source": path.name}]}

    def load_docx_file(self, path, scan_root=None):
        return {"chunks": ["docx"], "metadatas": [{"source": path.name}]}


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("guide.PDF", "pdf"),
        ("guide.txt", "text"),
        ("guide.md", "markdown"),
        ("guide.docx", "docx"),
    ],
)
def test_load_document_dispatches_by_format(filename, expected, tmp_path):
    path = tmp_path / filename
    chunks, metadatas = load_document(
        path,
        pdf_loader=PdfLoader(),
        wiki_loader=WikiLoader(),
    )
    assert chunks == [expected]
    assert metadatas == [{"source": filename}]


def test_load_document_rejects_unsupported_format(tmp_path):
    with pytest.raises(ValueError, match="Unsupported document format"):
        load_document(tmp_path / "data.csv")


def test_load_document_rejects_mismatched_chunks_and_metadata(tmp_path):
    class InvalidLoader:
        def load_markdown_file(self, path, scan_root=None):
            return {"chunks": ["one", "two"], "metadatas": [{}]}

    with pytest.raises(ValueError, match="mismatched chunks and metadata"):
        load_document(tmp_path / "guide.md", wiki_loader=InvalidLoader())


def test_directory_ingestion_uses_injected_loaders_and_tracks_stats(tmp_path):
    for filename in ("one.pdf", "two.txt", "three.md", "four.docx"):
        (tmp_path / filename).write_text("placeholder", encoding="utf-8")

    class Manager:
        def add_chunks(self, chunks, metadatas):
            return [f"chunk-{index}" for index, _chunk in enumerate(chunks)]

    class FakePdfLoader:
        def __init__(self, chunk_size, chunk_overlap):
            pass

        def load_and_chunk(self, path, scan_root=None):
            return {"chunks": ["pdf"], "metadatas": [{"source": path.name}]}

    class FakeWikiLoader:
        def __init__(self, chunk_size, chunk_overlap):
            pass

        def _load(self, path):
            return {"chunks": [path.suffix], "metadatas": [{"source": path.name}]}

        def load_text_file(self, path, scan_root=None):
            return self._load(path)

        def load_markdown_file(self, path, scan_root=None):
            return self._load(path)

        def load_docx_file(self, path, scan_root=None):
            return self._load(path)

    stats = {}
    ingest_documents_dir(
        tmp_path,
        Manager(),
        stats,
        chunk_size=100,
        chunk_overlap=10,
        pdf_loader_cls=FakePdfLoader,
        wiki_loader_cls=FakeWikiLoader,
    )

    assert stats["total_chunks"] == 4
    assert stats["by_type"] == {"doc_pdf": 1, "doc_wiki": 3}
    assert set(stats["by_source"]) == {"one.pdf", "two.txt", "three.md", "four.docx"}
