"""Tests for markdown cleaning (formatting-artifact removal)."""

from arciv.core.parse.clean_markdown import (
    clean_markdown,
    clean_orphan_brackets,
    cleanup_lists,
    fix_missing_spaces,
    strip_bold_italic,
    strip_inline_code,
)


class TestInlineCode:
    def test_strip_keeps_content(self):
        assert strip_inline_code("use `pip install`") == "use pip install"

    def test_double_backticks_untouched(self):
        # Only single-backtick spans are targeted.
        text = "``not inline``"
        assert strip_inline_code(text) == text


class TestBoldItalic:
    def test_bold_double_star(self):
        assert strip_bold_italic("**bold**") == "bold"

    def test_italic_single_star(self):
        assert strip_bold_italic("*italic*") == "italic"

    def test_bold_italic_triple_star(self):
        assert strip_bold_italic("***both***") == "both"

    def test_underscore_bold(self):
        assert strip_bold_italic("__bold__") == "bold"

    def test_emphasis_never_pairs_across_lines(self):
        # Two unrelated asterisks in different paragraphs are not an italic
        # span; matching them would silently delete both and mangle the prose.
        text = "a *stray star\n\nand another* here"
        assert strip_bold_italic(text) == text

    def test_multiplication_prose_untouched(self):
        text = "5 * 3 = 15 and 2 * 2 = 4"
        assert strip_bold_italic(text) == text

    def test_star_bullets_untouched(self):
        text = "* first bullet\n* second bullet"
        assert strip_bold_italic(text) == text

    def test_emphasis_inside_bullet_line_stripped(self):
        assert strip_bold_italic("* item with *emphasis* word") == (
            "* item with emphasis word"
        )


class TestFixMissingSpaces:
    def test_inserts_space_after_colon(self):
        assert fix_missing_spaces("data:If") == "data: If"

    def test_inserts_space_after_period(self):
        assert fix_missing_spaces("end.Next") == "end. Next"

    def test_normal_text_unchanged(self):
        assert fix_missing_spaces("a normal sentence.") == "a normal sentence."

    def test_allcaps_names_untouched(self):
        assert fix_missing_spaces("Node.JS and U.S.A. remain") == (
            "Node.JS and U.S.A. remain"
        )

    def test_abbreviations_untouched(self):
        assert fix_missing_spaces("the U.S. Government") == "the U.S. Government"


class TestCleanupLists:
    def test_removes_empty_bullets(self):
        result = cleanup_lists("- \n- real item")
        assert "real item" in result
        # The empty bullet line itself must be gone
        assert not any(line.strip() == "-" for line in result.splitlines())

    def test_removes_empty_numbered(self):
        result = cleanup_lists("1. \n2. real item")
        assert "real item" in result
        assert not any(line.strip() == "1." for line in result.splitlines())

    def test_keeps_non_empty_items_intact(self):
        text = "- first item\n- second item"
        assert cleanup_lists(text) == text


class TestOrphanBrackets:
    def test_removes_empty_parens(self):
        assert "()" not in clean_orphan_brackets("text ()")

    def test_removes_empty_brackets(self):
        assert "[]" not in clean_orphan_brackets("text []")


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
