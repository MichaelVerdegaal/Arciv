import re
from typing import Self

# === Compiled Regex Patterns for Markdown Cleaning ===
# Most patterns use group 1 for the inner content.

# Inline or fenced code blocks
INLINE_CODE_RE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")

# Bold/Italic - ordered from most specific to least specific
BOLD_ITALIC_3STAR_RE = re.compile(r"\*{3}(.+?)\*{3}", re.DOTALL)
BOLD_ITALIC_3UNDER_RE = re.compile(r"_{3}(.+?)_{3}", re.DOTALL)
BOLD_ITALIC_MIXED1_RE = re.compile(r"\*{2}_(.+?)_\*{2}", re.DOTALL)
BOLD_ITALIC_MIXED2_RE = re.compile(r"_{2}\*(.+?)\*_{2}", re.DOTALL)
BOLD_2STAR_RE = re.compile(r"\*{2}(.+?)\*{2}", re.DOTALL)
BOLD_2UNDER_RE = re.compile(r"_{2}(.+?)_{2}", re.DOTALL)
ITALIC_STAR_RE = re.compile(r"(?<!\w)\*(.+?)\*(?!\w)", re.DOTALL)
ITALIC_UNDER_RE = re.compile(r"(?<!\w)_(.+?)_(?!\w)", re.DOTALL)

# List cleanup (removal only - no content to preserve)
EMPTY_BULLET_RE = re.compile(r"^[\-\*\+]\s*$", re.MULTILINE)
EMPTY_NUMBERED_RE = re.compile(r"^\d+\.\s*$", re.MULTILINE)
LIST_WITH_COLON_BULLET_RE = re.compile(r"^[\-\*\+]\s+:\s*.*$", re.MULTILINE)
LIST_WITH_COLON_NUMBERED_RE = re.compile(r"^\d+\.\s+:\s*.*$", re.MULTILINE)
ORPHANED_ASTERISK_RE = re.compile(r"^\s*\*\s*[×]*\s*$", re.MULTILINE)
EMPTY_NUMBERED_SEQUENCE_RE = re.compile(r"(?:\d+\.\s+){2,}")

# Orphan brackets (removal only)
EMPTY_PARENS_RE = re.compile(r"\(\s*\)")
EMPTY_BRACKETS_RE = re.compile(r"\[\s*\]")
STRAY_PAREN_AFTER_SPACE_RE = re.compile(r"(?<=\s)\)")
STRAY_PAREN_LINE_START_RE = re.compile(r"^\)", re.MULTILINE)

# Grouped patterns for batch operations
BOLD_ITALIC_PATTERNS = [
    BOLD_ITALIC_3STAR_RE,
    BOLD_ITALIC_3UNDER_RE,
    BOLD_ITALIC_MIXED1_RE,
    BOLD_ITALIC_MIXED2_RE,
    BOLD_2STAR_RE,
    BOLD_2UNDER_RE,
    ITALIC_STAR_RE,
    ITALIC_UNDER_RE,
]

LIST_CLEANUP_PATTERNS = [
    EMPTY_BULLET_RE,
    EMPTY_NUMBERED_RE,
    LIST_WITH_COLON_BULLET_RE,
    LIST_WITH_COLON_NUMBERED_RE,
    ORPHANED_ASTERISK_RE,
]


class MarkdownCleaner:
    """Extended pipeline for text cleaning and preparation.

    Uses a fluent API pattern for chaining operations.
    """

    def __init__(self, text: str):
        self.text = text

    def _apply(
        self,
        pattern: re.Pattern[str],
        keep_content: bool = True,
        content_group: int = 1,
    ) -> Self:
        """Apply a compiled regex substitution with flexible content handling.

        Args:
            pattern: Compiled regex pattern. If keep_content=True, must contain a capture group.
            keep_content: If True, replace match with captured group.
                          If False, remove the entire match.
            content_group: Which capture group contains the content (default 1).

        Returns:
            Self for method chaining.
        """
        replacement = rf"\{content_group}" if keep_content else ""
        self.text = pattern.sub(replacement, self.text)
        return self

    def _apply_many(
        self,
        patterns: list[re.Pattern[str]],
        keep_content: bool = True,
    ) -> Self:
        """Apply multiple compiled patterns sequentially with the same settings.

        Args:
            patterns: List of compiled regex patterns to apply in order.
            keep_content: If True, preserve captured content. If False, remove entirely.

        Returns:
            Self for method chaining.
        """
        for pattern in patterns:
            self._apply(pattern, keep_content=keep_content)
        return self

    # === Public API Methods ===

    def strip_inline_code(self) -> Self:
        """Remove inline code formatting markers, keeping the code content."""
        return self._apply(INLINE_CODE_RE, keep_content=True)

    def remove_inline_code(self) -> Self:
        """Remove inline code entirely, including the content."""
        return self._apply(INLINE_CODE_RE, keep_content=False)

    def strip_bold_italic(self) -> Self:
        """Remove bold and italic formatting markers, keeping the text content."""
        # Order matters: process combined formats before simple ones
        return self._apply_many(BOLD_ITALIC_PATTERNS, keep_content=True)

    def cleanup_lists(self) -> Self:
        """Remove empty and malformed list items."""
        # Multiline patterns for line-based matching
        self._apply_many(LIST_CLEANUP_PATTERNS, keep_content=False)
        # Non-multiline pattern for sequences
        self._apply(EMPTY_NUMBERED_SEQUENCE_RE, keep_content=False)
        # Final cleanup pass
        return self._apply(EMPTY_NUMBERED_RE, keep_content=False)

    def clean_orphan_brackets(self) -> Self:
        """Remove orphaned parentheses, brackets, and stray punctuation."""
        self._apply(EMPTY_PARENS_RE, keep_content=False)
        self._apply(EMPTY_BRACKETS_RE, keep_content=False)
        self._apply(STRAY_PAREN_AFTER_SPACE_RE, keep_content=False)
        return self._apply(STRAY_PAREN_LINE_START_RE, keep_content=False)


def clean_markdown(text: str) -> str:
    """Clean markdown text by removing formatting artifacts.

    Args:
        text: Raw markdown text to clean.

    Returns:
        Cleaned markdown text.
    """
    return (
        MarkdownCleaner(text)
        .strip_inline_code()
        .strip_bold_italic()
        .cleanup_lists()
        .clean_orphan_brackets()
        .text
    )
