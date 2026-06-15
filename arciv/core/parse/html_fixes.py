"""Site-specific fixes applied to HTML before content extraction.

The web is messy: some sites ship markup that breaks DOM parsing, others
carry UI chrome that trips trafilatura's boilerplate detection. Every
such exception lives here, in one of two flat lists, so the conversion
logic itself stays free of per-site knowledge:

- ``FIX_PATTERNS``: regexes removed from the raw HTML string before DOM
  parsing, for markup that corrupts the parse itself.
- ``PRUNE_XPATHS``: elements pruned from the DOM before extraction, for
  valid markup that extraction mishandles.

Each rule documents the site(s) it exists for and the failure it
prevents. Rules apply to every page, so they must be scoped tightly
enough (unambiguous ids/classes) to never match legitimate content. If a
rule ever needs to fire for one domain only, that is the moment to add
domain scoping — not before.
"""

import re

# -- raw HTML fixes (regex, applied before DOM parsing) --

# Next.js: __NEXT_DATA__ scripts can contain literal "</script>" inside JSON
# strings, causing the script to prematurely close and leak JSON into the
# document body. The lookahead ensures we capture until the real end.
NEXT_DATA_RE = re.compile(
    r"<script\s+id=[\"']__NEXT_DATA__[\"'][^>]*>.*?</script>(?=\s*<(?:script|/body|/html))",
    re.DOTALL | re.IGNORECASE,
)

FIX_PATTERNS: list[re.Pattern[str]] = [NEXT_DATA_RE]

# -- DOM prunes (XPath, applied before extraction) --

# MediaWiki (wikipedia.org and every other MediaWiki site): each section
# heading sits in a small wrapper div next to an "[edit]" link — the div's
# only link — so trafilatura's link-density pruning judges the whole div
# boilerplate and deletes it, heading included.
MEDIAWIKI_EDIT_SECTION_XPATH = '//span[contains(@class, "mw-editsection")]'

PRUNE_XPATHS: list[str] = [MEDIAWIKI_EDIT_SECTION_XPATH]


def fix_html(html_content: str) -> str:
    """Apply every raw-HTML regex fix.

    Args:
        html_content: Raw HTML string.

    Returns:
        The HTML with all matched markup removed.
    """
    for pattern in FIX_PATTERNS:
        html_content = pattern.sub("", html_content)
    return html_content
