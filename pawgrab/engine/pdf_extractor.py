"""PDF content extraction — converts PDF bytes to text/HTML for the scrape pipeline."""

from __future__ import annotations

import structlog

logger = structlog.get_logger()

_MAX_PDF_SIZE = 50 * 1024 * 1024  # 50 MB


def is_pdf_content(content_type: str, url: str) -> bool:
    """Check if a response is a PDF based on Content-Type or URL extension."""
    if content_type and "application/pdf" in content_type.lower():
        return True
    return url.rstrip("/").lower().endswith(".pdf")


def extract_pdf_text(pdf_bytes: bytes) -> tuple[str, str | None]:
    """Extract text from PDF bytes.

    Returns (text, warning). Warning is set for encrypted or empty PDFs.
    """
    if len(pdf_bytes) > _MAX_PDF_SIZE:
        return "", f"PDF too large ({len(pdf_bytes)} bytes, max {_MAX_PDF_SIZE})"

    try:
        import fitz  # pymupdf
    except ImportError:
        return "", "pymupdf not installed — cannot extract PDF text"

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        return "", f"Failed to open PDF: {exc}"

    try:
        if doc.is_encrypted:
            doc.close()
            return "", "PDF is encrypted — cannot extract text"

        pages = []
        for page in doc:
            text = page.get_text()
            if text and text.strip():
                pages.append(text.strip())
        doc.close()

        full_text = "\n\n".join(pages)
        if not full_text.strip():
            return "", "PDF contains no extractable text (possibly scanned/image-only)"

        return full_text, None
    except Exception as exc:
        doc.close()
        return "", f"PDF extraction error: {exc}"


def pdf_text_to_html(text: str) -> str:
    """Wrap extracted PDF text in minimal HTML for the existing pipeline."""
    paragraphs = text.split("\n\n")
    body = "\n".join(f"<p>{_escape(p)}</p>" for p in paragraphs if p.strip())
    return f"<html><head><title>PDF Document</title></head><body>\n{body}\n</body></html>"


def _escape(text: str) -> str:
    """Minimal HTML escaping."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
