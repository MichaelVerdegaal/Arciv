"""rules.py - URL-processing rules loaded from TOML (defaults + user file).

A rule is a match (a match type plus a pattern) and an ordered list of actions.
The match decides only whether the actions apply; the actions transform the URL
in sequence. Rules are walked in order and the first whose match fires wins:
its actions run, then rule processing stops. See PLAN.md item 3 and the packaged
``default_rules.toml`` for the shipped rules.

Loading puts the user's ``rules.toml`` (in the data dir) ahead of the packaged
defaults, so a user rule wins on first match. The match/action engine here is
pure; the structural checks, plumbing guards, and canonicalization around it
live in :mod:`arciv.core.fetch.url_processing`.
"""

import re
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from loguru import logger

# How a rule's pattern is compared to a URL.
MATCH_TYPES = ("domain", "host", "starts_with", "regex")
# What an action does to a matched URL.
ACTION_TYPES = ("skip", "prepend", "replace", "regex_replace")


@dataclass(frozen=True)
class Action:
    """One transform applied to a URL when its rule matches.

    Only the fields relevant to ``type`` carry meaning:

    - ``skip``: ``reason`` (shown to the user; optional).
    - ``prepend``: ``text`` placed in front of the whole URL.
    - ``replace``: literal ``old`` substring swapped for ``new``.
    - ``regex_replace``: ``pattern`` to ``replacement`` (``$1`` capture groups).
    """

    type: str
    reason: str = ""
    text: str = ""
    old: str = ""
    new: str = ""
    pattern: str = ""
    replacement: str = ""


@dataclass(frozen=True)
class Rule:
    """A match plus the actions to run when it fires.

    Attributes:
        name: Human label, shown by ``arciv rules list`` / ``test``.
        match_type: One of MATCH_TYPES (TOML key ``type``).
        pattern: The string compared to the URL per match_type (TOML key
            ``match``).
        actions: Actions applied in order on a match.
    """

    name: str
    match_type: str
    pattern: str
    actions: tuple[Action, ...] = ()


@dataclass(frozen=True)
class Skip:
    """An action's verdict to stop processing: the URL is not archived."""

    reason: str


@dataclass(frozen=True)
class RuleResult:
    """What the rule chain did to a URL.

    Attributes:
        url: The URL after the matching rule's actions, or None if skipped.
        rule: The rule that fired, or None if no rule matched.
        reason: The skip reason, if a skip action fired.
    """

    url: str | None
    rule: Rule | None
    reason: str | None


def _rule_matches(rule: Rule, url: str, netloc: str, domain: str) -> bool:
    """Whether ``rule``'s match fires for this URL.

    ``domain`` is the registrable domain (tldextract), ``netloc`` the exact
    host. A broken regex matches nothing rather than raising, so one bad user
    rule never crashes the run.
    """
    if rule.match_type == "domain":
        return domain == rule.pattern
    if rule.match_type == "host":
        return netloc == rule.pattern
    if rule.match_type == "starts_with":
        return url.startswith(rule.pattern)
    if rule.match_type == "regex":
        try:
            return bool(re.search(rule.pattern, url, re.IGNORECASE))
        except re.error:
            return False
    return False


_DOLLAR_REF_RE = re.compile(r"\$(?:(\$)|\{(\d+)\}|(\d+))")


def _expand_dollar_refs(replacement: str) -> str:
    r"""Translate a ``$1``-style replacement into ``re.sub``'s ``\1`` form.

    Rules reference capture groups with ``$1``, ``$2`` (and ``${1}``), but
    ``re.sub`` only understands ``\1``. Any backslashes in the text are escaped
    first so they stay literal, and ``$$`` yields a literal ``$``.
    """
    escaped = replacement.replace("\\", "\\\\")

    def repl(m: re.Match) -> str:
        if m.group(1):  # $$ -> literal $
            return "$"
        return "\\" + (m.group(2) or m.group(3))  # $1 / ${1} -> \1

    return _DOLLAR_REF_RE.sub(repl, escaped)


def _apply_action(action: Action, url: str) -> str | Skip:
    """Apply one action to a URL, returning the new URL or a Skip.

    An invalid ``regex_replace`` pattern is a no-op (returns the URL unchanged)
    rather than raising, matching ``_rule_matches``' tolerance for bad regexes.
    """
    if action.type == "skip":
        return Skip(action.reason or "skipped (not content)")
    if action.type == "prepend":
        return action.text + url
    if action.type == "replace":
        return url.replace(action.old, action.new)
    if action.type == "regex_replace":
        try:
            return re.sub(
                action.pattern,
                _expand_dollar_refs(action.replacement),
                url,
                count=1,
                flags=re.IGNORECASE,
            )
        except re.error:
            return url
    return url


def apply_rules(
    url: str, netloc: str, domain: str, rules: Sequence[Rule]
) -> RuleResult:
    """Run the rule chain on a URL: the first matching rule wins.

    The first rule whose match fires has its actions applied in order; a skip
    action returns immediately with no URL, otherwise the transformed URL is
    returned. Rules after the first match are not considered.
    """
    for rule in rules:
        if not _rule_matches(rule, url, netloc, domain):
            continue
        current = url
        for action in rule.actions:
            outcome = _apply_action(action, current)
            if isinstance(outcome, Skip):
                return RuleResult(url=None, rule=rule, reason=outcome.reason)
            current = outcome
        return RuleResult(url=current, rule=rule, reason=None)
    return RuleResult(url=url, rule=None, reason=None)


def _parse_rules(text: str) -> list[Rule]:
    """Parse a TOML document of ``[[rule]]`` tables into Rule objects.

    A rule with an unknown match type or no pattern is dropped, and an action
    with an unknown type is skipped; both warn rather than raising, so one
    malformed entry in a hand-edited file doesn't take down the whole pipeline.
    """
    data = tomllib.loads(text)
    rules: list[Rule] = []
    for entry in data.get("rule", []):
        name = entry.get("name", "")
        match_type = entry.get("type", "")
        pattern = entry.get("match", "")
        if match_type not in MATCH_TYPES or not pattern:
            logger.warning(f"Skipping rule {name or entry!r}: bad type or empty match")
            continue
        actions: list[Action] = []
        for action in entry.get("action", []):
            action_type = action.get("type", "")
            if action_type not in ACTION_TYPES:
                logger.warning(
                    f"Skipping action in rule {name!r}: bad type {action_type!r}"
                )
                continue
            actions.append(
                Action(
                    type=action_type,
                    reason=action.get("reason", ""),
                    text=action.get("text", ""),
                    old=action.get("old", ""),
                    new=action.get("new", ""),
                    pattern=action.get("pattern", ""),
                    replacement=action.get("replacement", ""),
                )
            )
        rules.append(
            Rule(
                name=name,
                match_type=match_type,
                pattern=pattern,
                actions=tuple(actions),
            )
        )
    return rules


# The packaged defaults are static, so parse them once at import.
_DEFAULT_RULES: tuple[Rule, ...] = tuple(
    _parse_rules(
        resources.files(__package__)
        .joinpath("default_rules.toml")
        .read_text(encoding="utf-8")
    )
)

# Per-process cache of parsed user rules, keyed by path. The stored
# (mtime_ns, size, rules) is reused only while the file is unchanged, so an
# index run that calls load_rules once per source doesn't re-read and re-parse
# the same TOML each time, while an edit mid-process is still picked up.
_USER_RULES_CACHE: dict[Path, tuple[int, int, tuple[Rule, ...]]] = {}


def _load_user_rules(user_path: Path) -> tuple[Rule, ...]:
    """Parse the user rules file, reusing the cache when it hasn't changed."""
    try:
        stat = user_path.stat()
    except OSError:
        return ()
    key = (stat.st_mtime_ns, stat.st_size)
    cached = _USER_RULES_CACHE.get(user_path)
    if cached is not None and cached[:2] == key:
        return cached[2]
    try:
        rules = tuple(_parse_rules(user_path.read_text(encoding="utf-8")))
    except (tomllib.TOMLDecodeError, OSError) as exc:
        logger.warning(f"Ignoring user rules at {user_path}: {exc}")
        return ()
    _USER_RULES_CACHE[user_path] = (*key, rules)
    return rules


def load_rules(user_path: Path | None = None) -> list[Rule]:
    """Load the active rule list: user rules first, then packaged defaults.

    User rules are read from ``user_path`` (the data dir's ``rules.toml``) when
    it exists and placed ahead of the defaults, so a user rule wins on first
    match. With ``user_path`` None or missing, only the packaged defaults apply.
    A malformed user file is ignored (with a warning) rather than crashing.

    The parsed user file is cached per path (invalidated by mtime/size), so
    repeated calls within a run reuse the parse instead of re-reading the TOML.
    """
    rules: list[Rule] = []
    if user_path is not None:
        rules.extend(_load_user_rules(user_path))
    rules.extend(_DEFAULT_RULES)
    return rules
