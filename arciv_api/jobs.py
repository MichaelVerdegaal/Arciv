"""In-process archive job queue and single background worker.

``POST /archive`` enqueues a slug; one worker (started in the app lifespan)
pulls slugs and runs the library's fetch then parse off the event loop. The
durable truth is the DB row; a job's phase is ephemeral UI progress.

A single worker is deliberate: ``parse_pending()`` clears every awaiting_parse
row, so concurrent workers would swallow each other's freshly fetched pages and
the per-slug "parsing" phase would become approximate. The library's public
fetch wraps ``asyncio.run()``, so it cannot be awaited from the running loop;
both fetch and parse therefore run via ``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from loguru import logger

from arciv.core.db import Page, PageDatabase, Rule
from arciv.core.pipeline import archive_urls, fetch_urls, parse_page, parse_pending
from arciv.core.index import register_urls
from arciv.core.fetch import process_url, slug_for_url


class Phase(str, Enum):
    """The live, in-memory phase of an archive job."""

    queued = "queued"
    fetching = "fetching"
    parsing = "parsing"
    done = "done"
    failed = "failed"


class Action(str, Enum):
    """What an enqueued job should run for its slug.

    ``archive`` is the first-time flow (fetch the pending URL, then parse the
    new pages). ``refetch`` and ``reparse`` re-run an already-known page from
    the page detail view: ``refetch`` re-downloads from the network then
    re-parses that one page, while ``reparse`` re-parses the raw file already
    on disk with no network traffic — the fast loop for trying out parse rules.
    """

    archive = "archive"
    refetch = "refetch"
    reparse = "reparse"


_ACTIVE = (Phase.queued, Phase.fetching, Phase.parsing)


@dataclass
class Job:
    slug: str
    url: str
    phase: Phase = Phase.queued
    action: Action = Action.archive
    error: str | None = None


def _default_load_rules(db_path: Path) -> tuple[Rule, ...]:
    """Load the URL rules. Opens read-write so a never-created archive gets its
    schema (and default rules) before the first submitted URL is processed."""
    with PageDatabase(db_path) as db:
        return tuple(db.list_rules())


def _default_register(db_path: Path, url: str, processed: str) -> Page | None:
    """Mirror ``arciv get``: ensure the row (no source/link), return it."""
    with PageDatabase(db_path) as db:
        register_urls(db, [url])
        return db.get(processed)


def _default_fetch(db_path: Path, url: str) -> None:
    with PageDatabase(db_path) as db:
        fetch_urls(db, [url])


def _default_refetch(db_path: Path, url: str) -> None:
    """Re-download a single known page, replacing its raw file on disk."""
    with PageDatabase(db_path) as db:
        fetch_urls(db, [url], refetch=True)


def _default_parse(db_path: Path) -> None:
    with PageDatabase(db_path) as db:
        parse_pending(db)


def _default_reparse(db_path: Path, url: str) -> None:
    """Re-parse one page from its raw file on disk, whatever its parse state.

    ``parse_pending`` only touches unparsed pages, so a re-parse (or the parse
    after a re-fetch, which leaves ``parsed_at`` set) has to target the single
    page directly. No network traffic — everything is read from disk.
    """
    with PageDatabase(db_path) as db:
        page = db.get(url)
        if page is not None:
            parse_page(db, page)


def _default_archive_urls(db_path: Path, urls: list[str]) -> None:
    """Fetch then parse a batch of URLs through one shared browser context.

    The batch is the whole point: a source's URLs download concurrently under
    a single Fetcher run, not a browser launch per URL.
    """
    with PageDatabase(db_path) as db:
        archive_urls(db, urls)


class ArchiveQueue:
    """A bounded, single-worker queue keyed by slug for idempotency.

    The fetch/parse/register callables are injectable so tests can drive the
    flow without launching a real browser.
    """

    def __init__(
        self,
        db_path: Path,
        *,
        load_rules: Callable[[Path], tuple[Rule, ...]] = _default_load_rules,
        register: Callable[[Path, str, str], Page | None] = _default_register,
        fetch: Callable[[Path, str], None] = _default_fetch,
        refetch: Callable[[Path, str], None] = _default_refetch,
        parse: Callable[[Path], None] = _default_parse,
        reparse: Callable[[Path, str], None] = _default_reparse,
        archive_urls: Callable[[Path, list[str]], None] = _default_archive_urls,
        maxsize: int = 128,
    ) -> None:
        self._db_path = db_path
        self._load_rules = load_rules
        self._register = register
        self._fetch = fetch
        self._refetch = refetch
        self._parse = parse
        self._reparse = reparse
        self._archive_urls = archive_urls
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=maxsize)
        self._jobs: dict[str, Job] = {}
        self._task: asyncio.Task[None] | None = None
        # Background source archives run outside the single-slug worker: each
        # fetches a whole source's URLs in one batch. Track the live ones so the
        # UI can show "archiving" and keep task refs so they are not GC'd.
        self._active_sources: set[str] = set()
        self._source_tasks: set[asyncio.Task[None]] = set()

    def job_for(self, slug: str) -> Job | None:
        """The live job for a slug, or None if none is tracked."""
        return self._jobs.get(slug)

    def is_archiving(self, name: str) -> bool:
        """Whether a source's background archival is still running."""
        return name in self._active_sources

    def archive_source_bg(self, name: str, urls: list[str]) -> None:
        """Fetch and parse a source's URLs in the background.

        The caller registers and indexes the source first (so its files and
        links are visible immediately); this runs only the slow fetch+parse,
        off the request, as one batch.
        """
        self._active_sources.add(name)
        task = asyncio.create_task(self._run_source_archive(name, urls))
        self._source_tasks.add(task)
        task.add_done_callback(self._source_tasks.discard)

    async def _run_source_archive(self, name: str, urls: list[str]) -> None:
        try:
            if urls:
                await asyncio.to_thread(self._archive_urls, self._db_path, urls)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a failed archive must not crash the app
            logger.exception(f"Background archival failed for source {name!r}")
        finally:
            self._active_sources.discard(name)

    async def submit(self, url: str) -> tuple[str | None, str]:
        """Register the URL and enqueue a job.

        Returns ``(slug, outcome)`` where outcome is ``"done"`` (already
        parsed), ``"existing"`` (a job is in flight), or ``"queued"``; or
        ``(None, skip_reason)`` when ``process_url`` rejects the URL.
        """
        rules = await asyncio.to_thread(self._load_rules, self._db_path)
        processed, reason = process_url(url, rules)
        if processed is None:
            return None, reason
        slug = slug_for_url(processed)
        page = await asyncio.to_thread(self._register, self._db_path, url, processed)
        if page is not None and page.parsed_at is not None:
            return slug, "done"
        existing = self._jobs.get(slug)
        if existing is not None and existing.phase in _ACTIVE:
            return slug, "existing"
        self._jobs[slug] = Job(slug=slug, url=processed)
        await self._queue.put(slug)
        return slug, "queued"

    async def resubmit(self, slug: str, url: str, *, refetch: bool) -> str:
        """Re-run a known page: ``refetch`` re-downloads then re-parses, else
        re-parses the raw file on disk only.

        Idempotent — if a job for the slug is already in flight, nothing new is
        enqueued. Returns the outcome (``"refetch"``, ``"reparse"``, or
        ``"existing"``) for the caller to surface or ignore.
        """
        existing = self._jobs.get(slug)
        if existing is not None and existing.phase in _ACTIVE:
            return "existing"
        action = Action.refetch if refetch else Action.reparse
        self._jobs[slug] = Job(slug=slug, url=url, action=action)
        await self._queue.put(slug)
        return action.value

    async def _run(self) -> None:
        while True:
            slug = await self._queue.get()
            job = self._jobs.get(slug)
            if job is None:
                self._queue.task_done()
                continue
            try:
                await self._run_job(job)
                job.phase = Phase.done
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a failed job must not kill the worker
                job.phase = Phase.failed
                job.error = str(exc)
                logger.exception(f"Archive job failed for {slug}")
            finally:
                self._queue.task_done()

    async def _run_job(self, job: Job) -> None:
        """Run one job's stages by action, advancing its phase as it goes.

        A re-parse skips the network entirely; a re-fetch re-downloads then
        re-parses that one page (its row is still parsed, so the batch parse
        would skip it); a first-time archive fetches the pending URL then parses
        whatever became fetched.
        """
        if job.action is Action.reparse:
            job.phase = Phase.parsing
            await asyncio.to_thread(self._reparse, self._db_path, job.url)
            return
        job.phase = Phase.fetching
        if job.action is Action.refetch:
            await asyncio.to_thread(self._refetch, self._db_path, job.url)
            job.phase = Phase.parsing
            await asyncio.to_thread(self._reparse, self._db_path, job.url)
        else:
            await asyncio.to_thread(self._fetch, self._db_path, job.url)
            job.phase = Phase.parsing
            await asyncio.to_thread(self._parse, self._db_path)

    def start(self) -> None:
        """Start the worker task (idempotent)."""
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Cancel the worker and any background source archives, then wait."""
        tasks = [t for t in (self._task, *self._source_tasks) if t is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._source_tasks.clear()
        self._active_sources.clear()
