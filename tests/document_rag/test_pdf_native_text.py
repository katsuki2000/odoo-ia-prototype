from pypdf import PdfReader

from document_rag.ingestion.pdf_loader import PDFLoader, extract_pages_text
from tests.document_rag.pdf_samples import write_text_pdf


def test_extract_pages_text_returns_marked_pages(tmp_path):
    write_text_pdf(tmp_path / "guide.pdf", ["Guide", "- premier point"])
    text = extract_pages_text(PdfReader(str(tmp_path / "guide.pdf")))
    assert text.startswith("--- Page 1 ---\n")
    assert "premier point" in text


def test_extract_pages_text_is_empty_without_native_text(tmp_path):
    write_text_pdf(tmp_path / "scan.pdf", [])
    assert extract_pages_text(PdfReader(str(tmp_path / "scan.pdf"))) == ""


def test_loader_uses_the_shared_page_text_extraction(tmp_path):
    write_text_pdf(tmp_path / "guide.pdf", ["Guide", "- premier point"])
    reader = PdfReader(str(tmp_path / "guide.pdf"))
    assert PDFLoader()._extract_text_from_pdf(reader) == extract_pages_text(reader)
