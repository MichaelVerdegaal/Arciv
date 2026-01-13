import re
from typing import Self


class MarkdownCleaner:
    """Extended pipeline for text cleaning and preparation.

    Uses a fluent API pattern for chaining operations.
    """

    # === Pattern Constants ===
    # Most patterns use group 1 for the inner content.

    # Inline or fenced code blocks
    INLINE_CODE_RE = r"(?<!`)`([^`\n]+)`(?!`)"

    # Bold/Italic - ordered from most specific to least specific
    BOLD_ITALIC_3STAR_RE = r"\*{3}(.+?)\*{3}"
    BOLD_ITALIC_3UNDER_RE = r"_{3}(.+?)_{3}"
    BOLD_ITALIC_MIXED1_RE = r"\*{2}_(.+?)_\*{2}"
    BOLD_ITALIC_MIXED2_RE = r"_{2}\*(.+?)\*_{2}"
    BOLD_2STAR_RE = r"\*{2}(.+?)\*{2}"
    BOLD_2UNDER_RE = r"_{2}(.+?)_{2}"
    ITALIC_STAR_RE = r"(?<!\w)\*(.+?)\*(?!\w)"
    ITALIC_UNDER_RE = r"(?<!\w)_(.+?)_(?!\w)"

    # List cleanup (removal only - no content to preserve)
    EMPTY_BULLET_RE = r"^[\-\*\+]\s*$"
    EMPTY_NUMBERED_RE = r"^\d+\.\s*$"
    LIST_WITH_COLON_BULLET_RE = r"^[\-\*\+]\s+:\s*.*$"
    LIST_WITH_COLON_NUMBERED_RE = r"^\d+\.\s+:\s*.*$"
    ORPHANED_ASTERISK_RE = r"^\s*\*\s*[×]*\s*$"
    EMPTY_NUMBERED_SEQUENCE_RE = r"(?:\d+\.\s+){2,}"

    # Orphan brackets (removal only)
    EMPTY_PARENS_RE = r"\(\s*\)"
    EMPTY_BRACKETS_RE = r"\[\s*\]"
    STRAY_PAREN_AFTER_SPACE_RE = r"(?<=\s)\)"
    STRAY_PAREN_LINE_START_RE = r"^\)"

    def __init__(self, text: str):
        self.text = text

    def _apply(
        self,
        pattern: str,
        keep_content: bool = True,
        flags: re.RegexFlag = re.NOFLAG,
        content_group: int = 1,
    ) -> Self:
        """Apply a regex substitution with flexible content handling.

        Args:
            pattern: Regex pattern. If keep_content=True, must contain a capture group.
            keep_content: If True, replace match with captured group.
                          If False, remove the entire match.
            flags: Regex flags (e.g., re.MULTILINE, re.DOTALL).
            content_group: Which capture group contains the content (default 1).

        Returns:
            Self for method chaining.
        """
        replacement = rf"\{content_group}" if keep_content else ""
        self.text = re.sub(pattern, replacement, self.text, flags=flags)
        return self

    def _apply_many(
        self,
        patterns: list[str],
        keep_content: bool = True,
        flags: re.RegexFlag = re.NOFLAG,
    ) -> Self:
        """Apply multiple patterns sequentially with the same settings.

        Args:
            patterns: List of regex patterns to apply in order.
            keep_content: If True, preserve captured content. If False, remove entirely.
            flags: Regex flags applied to all patterns.

        Returns:
            Self for method chaining.
        """
        for pattern in patterns:
            self._apply(pattern, keep_content=keep_content, flags=flags)
        return self

    # === Public API Methods ===

    def strip_inline_code(self) -> Self:
        """Remove inline code formatting markers, keeping the code content."""
        return self._apply(self.INLINE_CODE_RE, keep_content=True)

    def remove_inline_code(self) -> Self:
        """Remove inline code entirely, including the content."""
        return self._apply(self.INLINE_CODE_RE, keep_content=False)

    def strip_bold_italic(self) -> Self:
        """Remove bold and italic formatting markers, keeping the text content."""
        # Order matters: process combined formats before simple ones
        return self._apply_many(
            [
                self.BOLD_ITALIC_3STAR_RE,
                self.BOLD_ITALIC_3UNDER_RE,
                self.BOLD_ITALIC_MIXED1_RE,
                self.BOLD_ITALIC_MIXED2_RE,
                self.BOLD_2STAR_RE,
                self.BOLD_2UNDER_RE,
                self.ITALIC_STAR_RE,
                self.ITALIC_UNDER_RE,
            ],
            keep_content=True,
            flags=re.DOTALL,
        )

    def cleanup_lists(self) -> Self:
        """Remove empty and malformed list items."""
        # Multiline patterns for line-based matching
        self._apply_many(
            [
                self.EMPTY_BULLET_RE,
                self.EMPTY_NUMBERED_RE,
                self.LIST_WITH_COLON_BULLET_RE,
                self.LIST_WITH_COLON_NUMBERED_RE,
                self.ORPHANED_ASTERISK_RE,
            ],
            keep_content=False,
            flags=re.MULTILINE,
        )
        # Non-multiline pattern for sequences
        self._apply(self.EMPTY_NUMBERED_SEQUENCE_RE, keep_content=False)
        # Final cleanup pass
        return self._apply(
            self.EMPTY_NUMBERED_RE, keep_content=False, flags=re.MULTILINE
        )

    def clean_orphan_brackets(self) -> Self:
        """Remove orphaned parentheses, brackets, and stray punctuation."""
        self._apply(self.EMPTY_PARENS_RE, keep_content=False)
        self._apply(self.EMPTY_BRACKETS_RE, keep_content=False)
        self._apply(self.STRAY_PAREN_AFTER_SPACE_RE, keep_content=False)
        return self._apply(
            self.STRAY_PAREN_LINE_START_RE, keep_content=False, flags=re.MULTILINE
        )
