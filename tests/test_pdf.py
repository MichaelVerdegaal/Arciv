"""Tests for PDF-to-text extraction (liteparse wrapper)."""

import pytest
from liteparse.types import ParseError

from arciv.core.parse.pdf import pdf_to_text


def test_extracts_text_layer(make_pdf):
    text = pdf_to_text(make_pdf("Hello world from an archived PDF"))
    assert text == "Hello world from an archived PDF"


def test_strips_surrounding_whitespace(make_pdf):
    # The content stream pads the text with spaces; pdf_to_text must trim.
    text = pdf_to_text(make_pdf("   padded text   "))
    assert text == text.strip()
    assert "padded text" in text


def test_corrupt_bytes_raise(make_pdf):
    # A non-PDF blob must surface the parser error, not be swallowed: the
    # parse stage relies on the exception to mark the page failed.
    with pytest.raises(ParseError):
        pdf_to_text(b"this is plainly not a pdf")
