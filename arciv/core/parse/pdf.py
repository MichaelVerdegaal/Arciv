"""PDF to text conversion using liteparse."""

from liteparse import LiteParse

_pdf_parser = LiteParse(ocr_enabled=False, quiet=True)


def pdf_to_text(pdf_bytes: bytes) -> str:
    """Extract plain text from PDF bytes.

    Args:
        pdf_bytes: Raw PDF file content.

    Returns:
        Extracted text, stripped of surrounding whitespace.

    Raises:
        Exception: Propagates liteparse errors (corrupt/unreadable PDFs).
    """
    result = _pdf_parser.parse(pdf_bytes)
    return result.text.strip()
