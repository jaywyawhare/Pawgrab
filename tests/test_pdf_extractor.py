"""Tests for PDF content extraction."""

import pytest

from pawgrab.engine.pdf_extractor import (
    _MAX_PDF_SIZE,
    extract_pdf_text,
    is_pdf_content,
    pdf_text_to_html,
)


class TestIsPdfContent:
    def test_content_type_application_pdf(self):
        assert is_pdf_content("application/pdf", "https://example.com/doc") is True

    def test_content_type_with_charset(self):
        assert is_pdf_content("application/pdf; charset=utf-8", "https://example.com/doc") is True

    def test_url_extension(self):
        assert is_pdf_content("", "https://example.com/paper.pdf") is True

    def test_url_extension_case_insensitive(self):
        assert is_pdf_content("", "https://example.com/paper.PDF") is True

    def test_not_pdf(self):
        assert is_pdf_content("text/html", "https://example.com/page") is False

    def test_empty_inputs(self):
        assert is_pdf_content("", "") is False


class TestExtractPdfText:
    def test_real_pdf_extraction(self):
        """Create a minimal PDF with pymupdf and extract its text."""
        import fitz

        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Hello PDF World")
        pdf_bytes = doc.tobytes()
        doc.close()

        text, warning = extract_pdf_text(pdf_bytes)
        assert "Hello PDF World" in text
        assert warning is None

    def test_empty_pdf(self):
        """PDF with no text content returns warning."""
        import fitz

        doc = fitz.open()
        doc.new_page()  # blank page
        pdf_bytes = doc.tobytes()
        doc.close()

        text, warning = extract_pdf_text(pdf_bytes)
        assert text == ""
        assert "no extractable text" in warning

    def test_oversized_pdf(self):
        """PDFs exceeding size limit are rejected."""
        huge = b"%" * (_MAX_PDF_SIZE + 1)
        text, warning = extract_pdf_text(huge)
        assert text == ""
        assert "too large" in warning

    def test_corrupted_pdf(self):
        """Corrupted bytes produce a warning."""
        text, warning = extract_pdf_text(b"not a pdf at all")
        assert text == ""
        assert warning is not None


class TestPdfTextToHtml:
    def test_wraps_paragraphs(self):
        html = pdf_text_to_html("First paragraph\n\nSecond paragraph")
        assert "<p>First paragraph</p>" in html
        assert "<p>Second paragraph</p>" in html
        assert "<html>" in html

    def test_escapes_html(self):
        html = pdf_text_to_html("x < y & z > w")
        assert "&lt;" in html
        assert "&amp;" in html
        assert "&gt;" in html

    def test_empty_text(self):
        html = pdf_text_to_html("")
        assert "<html>" in html
        assert "<body>" in html
