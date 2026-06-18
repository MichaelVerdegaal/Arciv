"""Data models for tracked pages and registered sources."""

import re
from dataclasses import dataclass

# Prefix of the fail_reason written when a page is rejected purely for being
# below the word-count threshold (see arciv.core.pipeline.parse). Such a page was
# fetched and extracted fine (it is just too small to be worth keeping), so
# the UI surfaces it as "skipped" rather than lumping it in with real errors
# (block pages, extraction failures, fetch timeouts). The classifier lives
# here so Page.state and the SQL filter in PageDatabase share one definition.
SKIP_REASON_PREFIX = "too short"


def is_skip_reason(fail_reason: str | None) -> bool:
    """Whether a fail_reason marks a deliberate skip (too-short content)
    rather than an error."""
    return fail_reason is not None and fail_reason.startswith(SKIP_REASON_PREFIX)


@dataclass
class Page:
    """A tracked web page in the database.

    Raw content lives on disk at ``saved/<slug>/page.html`` (or
    ``page.pdf``), parsed markdown at ``saved/<slug>/page.md``. The
    database holds pointers and pipeline state.

    Pipeline state is carried by the timestamps plus ``fail_reason``:

    - pending:        ``fetched_at`` NULL, ``fail_reason`` NULL
    - fetch failed:   ``fetched_at`` NULL, ``fail_reason`` set
    - fetched:        ``fetched_at`` set, ``parsed_at`` NULL
    - parse rejected: ``fetched_at`` set, ``parsed_at`` NULL, ``fail_reason`` set
    - parsed:         ``parsed_at`` set

    Attributes:
        url: The processed/normalized URL (primary key).
        original_url: Pre-normalization URL (before rewrites).
        domain: tldextract registered domain.
        slug: Folder name under ``saved/``, e.g. ``github.com-a1b2c3d4``.
        content_type: Raw file format on disk: "html" or "pdf". Set by the
            fetch stage; None while pending.
        title: HTML page title (filled in by the parse stage).
        author: Page author, if extractable (filled in by the parse stage).
        word_count: Number of words in markdown content (parse stage).
        fail_reason: Why fetching/parsing failed, if applicable.
        added_at: ISO timestamp of when the URL first entered the database.
        fetched_at: ISO timestamp of the last successful fetch.
        parsed_at: ISO timestamp of the last successful parse.
    """

    url: str
    original_url: str
    domain: str = ""
    slug: str = ""
    content_type: str | None = None
    title: str | None = None
    author: str | None = None
    word_count: int = 0
    fail_reason: str | None = None
    added_at: str | None = None
    fetched_at: str | None = None
    parsed_at: str | None = None

    @property
    def fetched(self) -> bool:
        """Whether raw content has been archived on disk."""
        return self.fetched_at is not None

    @property
    def parsed(self) -> bool:
        """Whether the raw content has been converted to markdown."""
        return self.parsed_at is not None

    @property
    def state(self) -> str:
        """Coarse UI state for the web browse view: ``"done"``,
        ``"skipped"``, ``"failed"``, ``"fetched"``, or ``"pending"``.

        A coarsening of the pipeline states above into what the UI shows:
        ``done`` is parsed, ``skipped`` is content rejected only for being
        too short (a clean fetch+extract, just below the threshold),
        ``failed`` is any other fetch or parse failure, ``fetched`` is raw
        content on disk still awaiting parse (no failure), and ``pending`` is
        not fetched yet. A parse never both succeeds and fails, so checking
        ``parsed_at`` first is just defensive ordering.
        """
        if self.parsed_at is not None:
            return "done"
        if is_skip_reason(self.fail_reason):
            return "skipped"
        if self.fail_reason is not None:
            return "failed"
        if self.fetched_at is not None:
            return "fetched"
        return "pending"


# Recognised rule match types and actions. Defined next to Rule so the URL
# processor, the database seeder, and the web form all validate against one
# list instead of three drifting copies.
RULE_MATCH_TYPES = ("domain", "host", "starts_with", "ends_with", "exact", "regex")
RULE_ACTIONS = ("skip", "rewrite")

# Capture-group references in a regex rewrite replacement: ``$1``, ``${1}``,
# with ``$$`` as a literal ``$`` escape (group 1 of the match). Kept in sync
# with ``_expand_dollar_refs`` in arciv.core.fetch.url_processing, which does the
# actual ``$n`` -> ``\n`` translation; here it is used only to count the refs.
_REGEX_REF_RE = re.compile(r"\$(?:(\$)|\{(\d+)\}|(\d+))")


def validate_rule(
    match_type: str, pattern: str, action: str, replacement: str | None
) -> str | None:
    """Validate a rule's fields, returning an error message or None if valid.

    Shared by the web ``add_rule`` handler and the CLI ``rules add`` so the two
    entry points cannot drift (same reasoning as the single ``RULE_MATCH_TYPES``
    list). Beyond the presence checks, this catches a broken regex pattern or a
    capture-group reference past the pattern's group count at add time, instead
    of letting the rule silently never fire at processing time (the URL
    processor swallows ``re.error`` as a runtime backstop).

    Args:
        match_type: Candidate match type (checked against RULE_MATCH_TYPES).
        pattern: The match pattern (must be non-empty).
        action: Candidate action (checked against RULE_ACTIONS).
        replacement: The replacement/reason; required for rewrite.

    Returns:
        An error message describing the first problem found, or None if the
        rule is valid.
    """
    if match_type not in RULE_MATCH_TYPES:
        return (
            f"Unknown match type: {match_type!r}. "
            f"Choose one of: {', '.join(RULE_MATCH_TYPES)}."
        )
    if action not in RULE_ACTIONS:
        return f"Unknown action: {action!r}. Choose one of: {', '.join(RULE_ACTIONS)}."
    if not pattern:
        return "Enter a pattern to match."
    if action == "rewrite" and not replacement:
        return "A rewrite rule needs a replacement."

    if match_type == "regex":
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            return f"Invalid regex pattern: {exc}."
        if action == "rewrite" and replacement:
            for m in _REGEX_REF_RE.finditer(replacement):
                if m.group(1):  # $$ -> literal $, not a group reference
                    continue
                index = int(m.group(2) or m.group(3))
                if index > compiled.groups:
                    return (
                        f"Replacement references ${index} but the pattern has "
                        f"only {compiled.groups} capture group(s)."
                    )
    return None


@dataclass
class Rule:
    r"""A user-editable URL-processing rule (a match plus an action).

    Rules run as an ordered list while a URL is processed (see
    ``arciv.core.fetch.process_url``); the first rule whose pattern matches
    wins. ``match_type`` decides how ``pattern`` is compared to the URL:

    - ``domain``: the registered domain; ``youtube.com`` also matches
      ``m.youtube.com`` and ``www.youtube.com``.
    - ``host``: the exact hostname (port included), e.g.
      ``raw.githubusercontent.com``.
    - ``starts_with``: a URL prefix, e.g. ``https://localhost``.
    - ``ends_with``: a URL suffix matched against the whole URL string, e.g.
      ``.epub``. A trailing query defeats it: ``.pdf`` matches ``…/foo.pdf``
      but not ``…/foo.pdf?v=2``.
    - ``exact``: the whole URL.
    - ``regex``: a regular expression (case-insensitive). Supports capture
      groups in ``replacement`` as ``$1``, ``$2``, etc., e.g. pattern
      ``^https://arxiv\.org/abs/(.*)$`` with replacement
      ``https://arxiv.org/pdf/$1``.

    ``action`` is what happens on a match:

    - ``skip``: the URL is not archived; ``replacement`` holds the reason
      shown to the user (optional, a generic reason is used if blank).
    - ``rewrite``: replaces whatever the match selected, so ``replacement``
      stands in for a different span per match type:

      - ``domain``/``host``: swaps the netloc (host), keeping path and query.
      - ``starts_with``: replaces the matched prefix.
      - ``ends_with``: replaces the matched suffix (it can only swap a suffix,
        not strip it, since a replacement is required).
      - ``exact``: replaces the whole URL.
      - ``regex``: ``replacement`` can use ``$1``, ``$2``, etc. to refer to
        captured groups, enabling full URL rewrites like
        ``^https://arxiv\.org/abs/(.*)$`` → ``https://arxiv.org/pdf/$1``.

    Attributes:
        match_type: One of RULE_MATCH_TYPES.
        pattern: The string compared against the URL per match_type.
        action: One of RULE_ACTIONS.
        replacement: For skip, the reason (optional); for rewrite, the new
            span (host, prefix, suffix, whole URL, or regex replacement).
        position: Sort key for ordering; lower positions run first.
        id: Database row id, or None before the rule is inserted.
        added_at: ISO timestamp of when the rule was created.
    """

    match_type: str
    pattern: str
    action: str
    replacement: str | None = None
    position: int = 0
    id: int | None = None
    added_at: str | None = None


@dataclass
class Source:
    """A registered source: a named directory of files to index.

    Attributes:
        name: User-chosen unique name (primary key).
        path: Full normalized path of the directory.
        added_at: ISO timestamp of when the source was registered.
    """

    name: str
    path: str
    added_at: str
