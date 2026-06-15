"""Data models for tracked pages and registered sources."""

from dataclasses import dataclass

# Prefix of the fail_reason written when a page is rejected purely for being
# below the word-count threshold (see arciv.core.pipeline.parse). Such a page was
# fetched and extracted fine — it is just too small to be worth keeping — so
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
        ``"skipped"``, ``"failed"``, or ``"pending"``.

        A coarsening of the pipeline states above into what the UI shows:
        ``done`` is parsed, ``skipped`` is content rejected only for being
        too short (a clean fetch+extract, just below the threshold),
        ``failed`` is any other fetch or parse failure, and ``pending`` is
        everything still in flight. A parse never both succeeds and fails,
        so checking ``parsed_at`` first is just defensive ordering.
        """
        if self.parsed_at is not None:
            return "done"
        if is_skip_reason(self.fail_reason):
            return "skipped"
        if self.fail_reason is not None:
            return "failed"
        return "pending"


# Recognised rule match types and actions. Defined next to Rule so the URL
# processor, the database seeder, and the web form all validate against one
# list instead of three drifting copies.
RULE_MATCH_TYPES = ("domain", "host", "starts_with", "exact")
RULE_ACTIONS = ("skip", "rewrite")


@dataclass
class Rule:
    """A user-editable URL-processing rule (a match plus an action).

    Rules run as an ordered list while a URL is processed (see
    ``arciv.core.fetch.process_url``); the first rule whose pattern matches
    wins. ``match_type`` decides how ``pattern`` is compared to the URL:

    - ``domain``: the registered domain — ``youtube.com`` also matches
      ``m.youtube.com`` and ``www.youtube.com``.
    - ``host``: the exact hostname (port included), e.g.
      ``raw.githubusercontent.com``.
    - ``starts_with``: a URL prefix, e.g. ``https://localhost``.
    - ``exact``: the whole URL.

    ``action`` is what happens on a match:

    - ``skip``: the URL is not archived; ``replacement`` holds the reason
      shown to the user (optional, a generic reason is used if blank).
    - ``rewrite``: the URL's host is swapped for ``replacement`` (path and
      query kept) and processing continues down the chain.

    Attributes:
        match_type: One of RULE_MATCH_TYPES.
        pattern: The string compared against the URL per match_type.
        action: One of RULE_ACTIONS.
        replacement: For skip, the reason (optional); for rewrite, the new host.
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
