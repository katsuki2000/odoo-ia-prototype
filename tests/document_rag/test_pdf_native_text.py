from document_rag.ingestion.pdf_loader import PDFLoader, extract_native_text, strip_page_markers
from tests.pdf_samples import write_text_pdf


def test_extract_native_text_returns_marked_pages(tmp_path):
    write_text_pdf(tmp_path / "guide.pdf", ["Guide", "- premier point"])
    text = extract_native_text(tmp_path / "guide.pdf")
    assert text.startswith("--- Page 1 ---\n")
    assert "premier point" in text


def test_extract_native_text_is_empty_without_native_text(tmp_path):
    write_text_pdf(tmp_path / "scan.pdf", [])
    assert extract_native_text(tmp_path / "scan.pdf") == ""


def test_strip_page_markers_removes_native_and_ocr_markers():
    text = "--- Page 1 ---\nPremiere page\n\n--- Page 2 (OCR) ---\nDeuxieme page"
    assert strip_page_markers(text) == "Premiere page\n\nDeuxieme page"


def test_loader_and_native_extraction_share_the_page_text(tmp_path):
    write_text_pdf(tmp_path / "guide.pdf", ["Guide", "- premier point"])
    from pypdf import PdfReader

    reader = PdfReader(str(tmp_path / "guide.pdf"))
    assert PDFLoader()._extract_text_from_pdf(reader) == extract_native_text(tmp_path / "guide.pdf")
