import pytest

from document_rag.ingestion.document_loader import load_document


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
