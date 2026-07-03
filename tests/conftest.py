"""Shared test fixtures."""

import pytest


def _build_pdf(text: str) -> bytes:
    """Assemble a tiny single-page PDF whose text layer is ``text``.

    The xref table is omitted on purpose: liteparse rebuilds it, so this
    stays a readable template instead of a byte-offset bookkeeping exercise.
    """
    stream = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode("latin-1")
    return b"".join(
        [
            b"%PDF-1.4\n",
            b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
            b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n",
            b"4 0 obj\n<< /Length " + str(len(stream)).encode() + b" >>\nstream\n",
            stream,
            b"\nendstream\nendobj\n",
            b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
            b"trailer\n<< /Size 6 /Root 1 0 R >>\n%%EOF",
        ]
    )


@pytest.fixture
def make_pdf():
    """Factory returning PDF bytes with the given (single-line) text layer."""
    return _build_pdf
