"""Tests for markdown cleaning (formatting-artifact removal)."""

from arciv.core.parse.clean_markdown import MarkdownCleaner, clean_markdown


class TestInlineCode:
    def test_strip_keeps_content(self):
        assert MarkdownCleaner("use `pip install`").strip_inline_code().text == (
            "use pip install"
        )

    def test_double_backticks_untouched(self):
        # Only single-backtick spans are targeted.
        text = "``not inline``"
        assert MarkdownCleaner(text).strip_inline_code().text == text


class TestBoldItalic:
    def test_bold_double_star(self):
        assert MarkdownCleaner("**bold**").strip_bold_italic().text == "bold"

    def test_italic_single_star(self):
        assert MarkdownCleaner("*italic*").strip_bold_italic().text == "italic"

    def test_bold_italic_triple_star(self):
        assert MarkdownCleaner("***both***").strip_bold_italic().text == "both"

    def test_underscore_bold(self):
        assert MarkdownCleaner("__bold__").strip_bold_italic().text == "bold"


class TestFixMissingSpaces:
    def test_inserts_space_after_colon(self):
        assert MarkdownCleaner("data:If").fix_missing_spaces().text == "data: If"

    def test_inserts_space_after_period(self):
        assert MarkdownCleaner("end.Next").fix_missing_spaces().text == "end. Next"

    def test_normal_text_unchanged(self):
        assert MarkdownCleaner("a normal sentence.").fix_missing_spaces().text == (
            "a normal sentence."
        )


class TestCleanupLists:
    def test_removes_empty_bullets(self):
        result = MarkdownCleaner("- \n- real item").cleanup_lists().text
        assert "real item" in result
        # The empty bullet line itself must be gone
        assert not any(line.strip() == "-" for line in result.splitlines())

    def test_removes_empty_numbered(self):
        result = MarkdownCleaner("1. \n2. real item").cleanup_lists().text
        assert "real item" in result
        assert not any(line.strip() == "1." for line in result.splitlines())

    def test_keeps_non_empty_items_intact(self):
        text = "- first item\n- second item"
        assert MarkdownCleaner(text).cleanup_lists().text == text


class TestOrphanBrackets:
    def test_removes_empty_parens(self):
        assert "()" not in MarkdownCleaner("text ()").clean_orphan_brackets().text

    def test_removes_empty_brackets(self):
        assert "[]" not in MarkdownCleaner("text []").clean_orphan_brackets().text

    def test_preserves_alt_less_image(self):
        # The empty-bracket rule must not gut an alt-less markdown image; the
        # "!" in front of "[]" is what keeps it intact.
        text = "![](images/abc123.png)"
        assert MarkdownCleaner(text).clean_orphan_brackets().text == text
        assert clean_markdown(text) == text


class TestCleanMarkdownPipeline:
    def test_combined_cleaning(self):
        raw = "Use **bold** and `code` here.Next line"
        cleaned = clean_markdown(raw)
        assert "**" not in cleaned
        assert "`" not in cleaned
        assert "here. Next" in cleaned

    def test_idempotent_on_clean_text(self):
        text = "Plain text with nothing to clean."
        assert clean_markdown(text) == text
