"""Markdown cleanup for archived pages: strip extraction artifacts.

This cleanup is deliberately lossy: the archive stores plain readable
prose, so all bold, italic, and inline-code markers are stripped (their
text content is kept), malformed list items and orphan brackets left
behind by extraction are removed, and missing spaces after sentence
punctuation are restored. That is an irreversible editorial decision made
at archive time; the raw HTML stays on disk in the slug folder if the
original formatting is ever needed again.

Every emphasis pattern is bounded to a single line: emphasis never spans
paragraphs in real markdown, so a cross-line match is by definition a
false pair (two unrelated asterisks) and substituting it would corrupt
the prose between them.
"""

import re

# Compiled patterns for markdown cleaning. Most use group 1 for the inner content.

# Inline code span
INLINE_CODE_RE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")

# Bold/Italic - ordered from most specific to least specific. The inner group
# stays on one line and must start and end with a non-space (as real markdown
# emphasis does), so a stray "2 * 3" or a "*" list bullet never pairs with an
# unrelated marker further along the line.
BOLD_ITALIC_3STAR_RE = re.compile(r"\*{3}(\S(?:[^\n]*?\S)?)\*{3}")
BOLD_ITALIC_3UNDER_RE = re.compile(r"_{3}(\S(?:[^\n]*?\S)?)_{3}")
BOLD_ITALIC_MIXED1_RE = re.compile(r"\*{2}_(\S(?:[^\n]*?\S)?)_\*{2}")
BOLD_ITALIC_MIXED2_RE = re.compile(r"_{2}\*(\S(?:[^\n]*?\S)?)\*_{2}")
BOLD_2STAR_RE = re.compile(r"\*{2}(\S(?:[^\n]*?\S)?)\*{2}")
BOLD_2UNDER_RE = re.compile(r"_{2}(\S(?:[^\n]*?\S)?)_{2}")
ITALIC_STAR_RE = re.compile(r"(?<!\w)\*(\S(?:[^*\n]*\S)?)\*(?!\w)")
ITALIC_UNDER_RE = re.compile(r"(?<!\w)_(\S(?:[^_\n]*\S)?)_(?!\w)")

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

# Missing space after sentence punctuation ("data:If" -> "data: If"). Requires
# a lowercase letter before the punctuation and a capital-then-lowercase after,
# so abbreviations ("U.S.A"), all-caps names ("Node.JS"), and version strings
# stay intact. Dotted identifiers like "module.ClassName" still match; that is
# the accepted residual cost of fixing real concatenated sentences.
MISSING_SPACE_RE = re.compile(r"([a-z][.:;!?])([A-Z][a-z])")

# Order matters: combined formats before simple ones.
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

ORPHAN_BRACKET_PATTERNS = [
    EMPTY_PARENS_RE,
    EMPTY_BRACKETS_RE,
    STRAY_PAREN_AFTER_SPACE_RE,
    STRAY_PAREN_LINE_START_RE,
]


def strip_inline_code(text: str) -> str:
    """Remove inline code formatting markers, keeping the code content."""
    return INLINE_CODE_RE.sub(r"\1", text)


def strip_bold_italic(text: str) -> str:
    """Remove bold and italic formatting markers, keeping the text content."""
    for pattern in BOLD_ITALIC_PATTERNS:
        text = pattern.sub(r"\1", text)
    return text


def fix_missing_spaces(text: str) -> str:
    """Insert the space missing between a sentence end and the next capital.

    Fixes concatenated sentences like 'data:If' -> 'data: If'.
    """
    return MISSING_SPACE_RE.sub(r"\1 \2", text)


def cleanup_lists(text: str) -> str:
    """Remove empty and malformed list items."""
    for pattern in LIST_CLEANUP_PATTERNS:
        text = pattern.sub("", text)
    text = EMPTY_NUMBERED_SEQUENCE_RE.sub("", text)
    # Final pass: sequences can leave a lone "N." line behind
    return EMPTY_NUMBERED_RE.sub("", text)


def clean_orphan_brackets(text: str) -> str:
    """Remove orphaned parentheses, brackets, and stray punctuation."""
    for pattern in ORPHAN_BRACKET_PATTERNS:
        text = pattern.sub("", text)
    return text


def clean_markdown(text: str) -> str:
    """Clean markdown text by removing formatting artifacts.

    Args:
        text: Raw markdown text to clean.

    Returns:
        Cleaned markdown text.
    """
    text = strip_inline_code(text)
    text = strip_bold_italic(text)
    text = fix_missing_spaces(text)
    text = cleanup_lists(text)
    return clean_orphan_brackets(text)
