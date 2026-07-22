"""Tests for the CLI: command parity, stdout/stderr split, JSON, exit codes."""

import json
import sys
from datetime import UTC, datetime

import pytest
from loguru import logger
from typer.testing import CliRunner

import arciv.cli.cli as cli_module
from arciv.cli import output
from arciv.core.db import Page, PageDatabase, Source
from arciv.core.pipeline import ArchiveResult
from arciv.core.urls import slug_for_url
from arciv.settings import configure_logger


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Point the CLI at a temp data dir with a deterministic logger.

    The logger sink is synchronous (no enqueue) and writes only the
    message to stderr, so stdout/stderr assertions are stable. The global
    --json state is reset around each test.
    """

    def fake_configure(
        level: str = "INFO", color: str = "auto", log_file: bool = False
    ):
        logger.remove()
        logger.add(sys.stderr, level=level, format="{message}", enqueue=False)

    monkeypatch.setattr(cli_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cli_module, "DB_PATH", tmp_path / "arciv.db")
    monkeypatch.setattr(cli_module, "SAVED_DIR", tmp_path / "saved")
    monkeypatch.setattr(cli_module, "USER_RULES_PATH", tmp_path / "rules.toml")
    monkeypatch.setattr(cli_module, "configure_logger", fake_configure)
    output.set_json_output(False)
    yield tmp_path
    logger.remove()
    output.set_json_output(False)


def _page(url: str, **overrides) -> Page:
    # slug is unique per URL (slug_for_url is deterministic), matching
    # production and satisfying the slug UNIQUE constraint when a test
    # seeds several pages at once.
    defaults = dict(
        original_url=url,
        domain="example.com",
        slug=slug_for_url(url),
        content_type="html",
        word_count=500,
        fetched_at="2026-06-11T00:00:00+00:00",
    )
    defaults.update(overrides)
    return Page(url=url, **defaults)


def _seed(data_dir, pages: list[Page]) -> None:
    with PageDatabase(data_dir / "arciv.db") as db:
        for page in pages:
            db.upsert(page)


class TestList:
    def _seed_three(self, data_dir):
        _seed(
            data_dir,
            [
                _page(
                    "https://example.com/old",
                    fetched_at="2026-06-01T08:00:00+00:00",
                ),
                _page(
                    "https://example.com/mid",
                    fetched_at="2026-06-05T09:30:00+00:00",
                ),
                _page(
                    "https://example.com/new",
                    fetched_at="2026-06-10T10:15:00+00:00",
                ),
                _page("https://example.com/pending", fetched_at=None),
            ],
        )

    def test_rows_are_tab_separated_newest_first(self, runner, data_dir):
        self._seed_three(data_dir)
        result = runner.invoke(cli_module.cli, ["list"])
        assert result.exit_code == 0
        lines = result.output.splitlines()
        assert lines[0] == "2026-06-10T10:15:00\texample.com\thttps://example.com/new"
        assert [line.split("\t")[2] for line in lines] == [
            "https://example.com/new",
            "https://example.com/mid",
            "https://example.com/old",
        ]

    def test_n_limits_rows(self, runner, data_dir):
        self._seed_three(data_dir)
        result = runner.invoke(cli_module.cli, ["list", "-n", "1"])
        assert result.exit_code == 0
        assert result.output.splitlines() == [
            "2026-06-10T10:15:00\texample.com\thttps://example.com/new"
        ]

    def test_limit_long_form_limits_rows(self, runner, data_dir):
        self._seed_three(data_dir)
        result = runner.invoke(cli_module.cli, ["list", "--limit", "1"])
        assert result.exit_code == 0
        assert result.output.splitlines() == [
            "2026-06-10T10:15:00\texample.com\thttps://example.com/new"
        ]

    def test_old_double_dash_n_is_gone(self, runner, data_dir):
        self._seed_three(data_dir)
        result = runner.invoke(cli_module.cli, ["list", "--n", "1"])
        assert result.exit_code != 0

    def test_n_zero_shows_everything(self, runner, data_dir):
        self._seed_three(data_dir)
        result = runner.invoke(cli_module.cli, ["list", "-n", "0"])
        assert len(result.output.splitlines()) == 3

    def test_reverse_shows_oldest_first(self, runner, data_dir):
        self._seed_three(data_dir)
        result = runner.invoke(cli_module.cli, ["list", "--reverse"])
        first_urls = [line.split("\t")[2] for line in result.output.splitlines()]
        assert first_urls[0] == "https://example.com/old"
        assert first_urls[-1] == "https://example.com/new"

    def test_empty_archive_prints_nothing(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["list"])
        assert result.exit_code == 0
        assert result.output == ""

    def test_domain_filters_to_one_domain(self, runner, data_dir):
        _seed(
            data_dir,
            [
                _page(
                    "https://a.com/1",
                    domain="a.com",
                    fetched_at="2026-06-10T00:00:00+00:00",
                ),
                _page(
                    "https://b.com/1",
                    domain="b.com",
                    fetched_at="2026-06-11T00:00:00+00:00",
                ),
                _page(
                    "https://a.com/2",
                    domain="a.com",
                    fetched_at="2026-06-12T00:00:00+00:00",
                ),
            ],
        )
        result = runner.invoke(cli_module.cli, ["list", "--domain", "a.com"])
        assert result.exit_code == 0
        urls = [line.split("\t")[2] for line in result.output.splitlines()]
        assert urls == ["https://a.com/2", "https://a.com/1"]

    def test_source_filters_to_one_source(self, runner, data_dir, tmp_path):
        notes = tmp_path / "notes"
        notes.mkdir()
        _seed(
            data_dir,
            [
                _page("https://a.com/1", fetched_at="2026-06-10T00:00:00+00:00"),
                _page("https://a.com/2", fetched_at="2026-06-11T00:00:00+00:00"),
            ],
        )
        with PageDatabase(data_dir / "arciv.db") as db:
            db.add_source(Source("notes", str(notes), datetime.now(UTC).isoformat()))
            # Only /1 is indexed from the source; /2 was archived ad-hoc.
            db.replace_links_for_files(
                [],
                [("https://a.com/1", "n.md", "notes", "2026-06-01T00:00:00")],
            )
        result = runner.invoke(cli_module.cli, ["list", "--source", "notes"])
        assert result.exit_code == 0
        urls = [line.split("\t")[2] for line in result.output.splitlines()]
        assert urls == ["https://a.com/1"]

    def test_unknown_source_is_noinput(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["list", "--source", "ghost"])
        assert result.exit_code == output.EXIT_NOINPUT


class TestPath:
    def _seed_parsed(self, data_dir):
        page = _page(
            "https://example.com/post",
            parsed_at="2026-06-11T01:00:00+00:00",
        )
        _seed(data_dir, [page])
        md_path = data_dir / "saved" / page.slug / "page.md"
        md_path.parent.mkdir(parents=True)
        md_path.write_text("# Hello\n\nArchived text.\n", encoding="utf-8")
        return md_path

    def test_prints_markdown_filepath(self, runner, data_dir):
        md_path = self._seed_parsed(data_dir)
        result = runner.invoke(cli_module.cli, ["path", "https://example.com/post"])
        assert result.exit_code == 0
        assert result.output == f"{md_path}\n"

    def test_url_is_normalized_for_lookup(self, runner, data_dir):
        # Fragments are stripped at index time; path must match that
        md_path = self._seed_parsed(data_dir)
        result = runner.invoke(
            cli_module.cli, ["path", "https://example.com/post#section-2"]
        )
        assert result.exit_code == 0
        assert result.output == f"{md_path}\n"

    def test_unknown_url_fails(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["path", "https://example.com/nope"])
        assert result.exit_code != 0
        assert "Unknown URL" in result.output

    def test_pending_url_fails_with_hint(self, runner, data_dir):
        _seed(data_dir, [_page("https://example.com/post", fetched_at=None)])
        result = runner.invoke(cli_module.cli, ["path", "https://example.com/post"])
        assert result.exit_code != 0
        assert "arciv fetch" in result.output

    def test_unparsed_url_fails_with_hint(self, runner, data_dir):
        _seed(data_dir, [_page("https://example.com/post")])
        result = runner.invoke(cli_module.cli, ["path", "https://example.com/post"])
        assert result.exit_code != 0
        assert "arciv parse" in result.output

    def test_failed_url_reports_reason(self, runner, data_dir):
        _seed(
            data_dir,
            [
                _page(
                    "https://example.com/post",
                    fetched_at=None,
                    fail_reason="timeout",
                )
            ],
        )
        result = runner.invoke(cli_module.cli, ["path", "https://example.com/post"])
        assert result.exit_code != 0
        assert "timeout" in result.output

    def test_missing_file_on_disk_fails(self, runner, data_dir):
        # Row says parsed, but the markdown file is gone: don't print a
        # path that doesn't exist
        _seed(
            data_dir,
            [
                _page(
                    "https://example.com/post",
                    parsed_at="2026-06-11T01:00:00+00:00",
                )
            ],
        )
        result = runner.invoke(cli_module.cli, ["path", "https://example.com/post"])
        assert result.exit_code != 0
        assert "missing" in result.output


class TestStatus:
    def test_counts_without_recent_fetches(self, runner, data_dir):
        _seed(data_dir, [_page("https://example.com/a")])
        result = runner.invoke(cli_module.cli, ["status"])
        assert result.exit_code == 0
        assert "Pages: 1 total" in result.output
        # Recently fetched pages moved to `arciv list`
        assert "Recent fetches" not in result.output


class TestPrune:
    def _seed_with_folders(self, data_dir):
        """Seed an ok page and a failed page, each with a saved/<slug>/ folder."""
        pages = [
            _page("https://example.com/ok", parsed_at="2026-06-11T00:00:00+00:00"),
            _page("https://example.com/bad", fail_reason="timeout"),
        ]
        _seed(data_dir, pages)
        for page in pages:
            folder = data_dir / "saved" / page.slug
            folder.mkdir(parents=True)
            (folder / "page.html").write_text("x", encoding="utf-8")
        return pages

    def test_failed_force_deletes_row_and_folder(self, runner, data_dir):
        ok, bad = self._seed_with_folders(data_dir)
        result = runner.invoke(cli_module.cli, ["prune", "failed", "--force"])
        assert result.exit_code == 0
        assert "Pruned 1 page(s)" in result.output
        with PageDatabase(data_dir / "arciv.db") as db:
            assert db.get_all_urls() == ["https://example.com/ok"]
        assert not (data_dir / "saved" / bad.slug).exists()
        assert (data_dir / "saved" / ok.slug).exists()

    def test_nothing_to_prune_is_graceful(self, runner, data_dir):
        _seed(
            data_dir,
            [_page("https://example.com/ok", parsed_at="2026-06-11T00:00:00+00:00")],
        )
        result = runner.invoke(cli_module.cli, ["prune", "failed", "--force"])
        assert result.exit_code == 0
        assert "Nothing to prune" in result.output

    def test_asks_and_aborts_on_no(self, runner, data_dir):
        self._seed_with_folders(data_dir)
        result = runner.invoke(cli_module.cli, ["prune", "all"], input="n\n")
        assert result.exit_code != 0
        with PageDatabase(data_dir / "arciv.db") as db:
            assert db.count() == 2

    def test_invalid_mode_is_usage_error(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["prune", "everything"])
        assert result.exit_code != 0


class TestDbGroup:
    def test_dir_prints_data_dir(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["db", "dir"])
        assert result.exit_code == 0
        assert result.output.strip() == str(data_dir)

    def test_remove_force_deletes_db_and_sidecars(self, runner, data_dir):
        _seed(data_dir, [_page("https://example.com/a")])
        for suffix in ("-wal", "-shm"):
            (data_dir / f"arciv.db{suffix}").touch()
        result = runner.invoke(cli_module.cli, ["db", "remove", "--force"])
        assert result.exit_code == 0
        assert not (data_dir / "arciv.db").exists()
        assert not (data_dir / "arciv.db-wal").exists()
        assert not (data_dir / "arciv.db-shm").exists()

    def test_remove_asks_and_aborts_on_no(self, runner, data_dir):
        _seed(data_dir, [_page("https://example.com/a")])
        result = runner.invoke(cli_module.cli, ["db", "remove"], input="n\n")
        assert result.exit_code != 0
        assert (data_dir / "arciv.db").exists()

    def test_remove_asks_and_deletes_on_yes(self, runner, data_dir):
        _seed(data_dir, [_page("https://example.com/a")])
        result = runner.invoke(cli_module.cli, ["db", "remove"], input="y\n")
        assert result.exit_code == 0
        assert not (data_dir / "arciv.db").exists()

    def test_remove_without_db_is_graceful(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["db", "remove"])
        assert result.exit_code == 0
        assert "No database" in result.output

    def test_remove_keeps_saved_files_by_default(self, runner, data_dir):
        _seed(data_dir, [_page("https://example.com/a")])
        saved = data_dir / "saved" / "post"
        saved.mkdir(parents=True)
        (saved / "page.md").write_text("x", encoding="utf-8")
        result = runner.invoke(cli_module.cli, ["db", "remove", "--force"])
        assert result.exit_code == 0
        assert not (data_dir / "arciv.db").exists()
        assert saved.exists()

    def test_remove_files_deletes_saved_dir(self, runner, data_dir):
        _seed(data_dir, [_page("https://example.com/a")])
        saved = data_dir / "saved" / "post"
        saved.mkdir(parents=True)
        (saved / "page.md").write_text("x", encoding="utf-8")
        result = runner.invoke(
            cli_module.cli, ["db", "remove", "--force", "--remove-files"]
        )
        assert result.exit_code == 0
        assert not (data_dir / "arciv.db").exists()
        assert not (data_dir / "saved").exists()


class TestSourceGroup:
    """`source add` archives after registering; `source update` re-syncs one.

    The real archival launches a browser, so these replace ``archive_source``
    / ``archive_urls`` in the CLI module with fakes and assert the wiring.
    """

    def test_add_registers_and_archives(self, runner, data_dir, tmp_path, monkeypatch):
        notes = tmp_path / "notes"
        notes.mkdir()
        called = {}

        def fake_archive_source(db, name):
            called["name"] = name
            return ArchiveResult(urls=["https://a.com/1"], fetched=[], parsed=0)

        monkeypatch.setattr(cli_module, "archive_source", fake_archive_source)
        result = runner.invoke(cli_module.cli, ["source", "add", str(notes), "notes"])
        assert result.exit_code == 0
        assert called["name"] == "notes"
        with PageDatabase(data_dir / "arciv.db") as db:
            assert db.get_source("notes") is not None

    def test_add_no_archive_only_registers(
        self, runner, data_dir, tmp_path, monkeypatch
    ):
        notes = tmp_path / "notes"
        notes.mkdir()
        called = {}

        def fake_archive_source(db, name):
            called["name"] = name
            return ArchiveResult(urls=[], fetched=[], parsed=0)

        monkeypatch.setattr(cli_module, "archive_source", fake_archive_source)
        result = runner.invoke(
            cli_module.cli, ["source", "add", str(notes), "notes", "--no-archive"]
        )
        assert result.exit_code == 0
        assert "name" not in called  # archival was not triggered
        with PageDatabase(data_dir / "arciv.db") as db:
            assert db.get_source("notes") is not None

    def test_add_duplicate_name_fails(self, runner, data_dir, tmp_path, monkeypatch):
        notes = tmp_path / "notes"
        notes.mkdir()
        monkeypatch.setattr(
            cli_module,
            "archive_source",
            lambda db, name: ArchiveResult([], [], 0),
        )
        runner.invoke(
            cli_module.cli, ["source", "add", str(notes), "notes", "--no-archive"]
        )
        result = runner.invoke(
            cli_module.cli, ["source", "add", str(notes), "notes", "--no-archive"]
        )
        assert result.exit_code != 0
        assert "already exists" in result.output

    def test_update_source_invokes_pipeline(
        self, runner, data_dir, tmp_path, monkeypatch
    ):
        notes = tmp_path / "notes"
        notes.mkdir()
        with PageDatabase(data_dir / "arciv.db") as db:
            db.add_source(Source("notes", str(notes), datetime.now(UTC).isoformat()))
        called = {}

        def fake_archive_source(db, name):
            called["name"] = name
            return ArchiveResult(urls=["https://a.com/1"], fetched=[], parsed=1)

        monkeypatch.setattr(cli_module, "archive_source", fake_archive_source)
        result = runner.invoke(cli_module.cli, ["source", "update", "notes"])
        assert result.exit_code == 0
        assert called["name"] == "notes"

    def test_update_all_batches_every_source(
        self, runner, data_dir, tmp_path, monkeypatch
    ):
        notes = tmp_path / "notes"
        notes.mkdir()
        with PageDatabase(data_dir / "arciv.db") as db:
            db.add_source(Source("notes", str(notes), datetime.now(UTC).isoformat()))
        captured = {}
        monkeypatch.setattr(cli_module, "index_all", lambda db: ["https://a.com/1"])

        def fake_archive_urls(db, urls):
            captured["urls"] = urls
            return ArchiveResult(urls=urls, fetched=[], parsed=0)

        monkeypatch.setattr(cli_module, "archive_urls", fake_archive_urls)
        result = runner.invoke(cli_module.cli, ["source", "update", "--all"])
        assert result.exit_code == 0
        assert captured["urls"] == ["https://a.com/1"]

    def test_update_all_with_no_sources_is_graceful(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["source", "update", "--all"])
        assert result.exit_code == 0
        assert "No sources registered" in result.output

    def test_update_unknown_source_is_noinput(self, runner, data_dir):
        # No source registered: the real archive_source raises KeyError before
        # any fetch, so no browser is launched.
        result = runner.invoke(cli_module.cli, ["source", "update", "ghost"])
        assert result.exit_code == output.EXIT_NOINPUT

    def test_update_name_and_all_is_usage(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["source", "update", "notes", "--all"])
        assert result.exit_code == output.EXIT_USAGE

    def _register(self, data_dir, tmp_path, name="notes"):
        directory = tmp_path / name
        directory.mkdir(exist_ok=True)
        with PageDatabase(data_dir / "arciv.db") as db:
            db.add_source(Source(name, str(directory), datetime.now(UTC).isoformat()))

    def test_bare_source_lists_registered(self, runner, data_dir, tmp_path):
        self._register(data_dir, tmp_path, "notes")
        result = runner.invoke(cli_module.cli, ["source"])
        assert result.exit_code == 0
        assert result.stdout.splitlines()[0].split("\t")[0] == "notes"

    def test_source_list_matches_bare(self, runner, data_dir, tmp_path):
        self._register(data_dir, tmp_path, "notes")
        result = runner.invoke(cli_module.cli, ["source", "list"])
        assert result.exit_code == 0
        assert result.stdout.splitlines()[0].split("\t")[0] == "notes"

    def test_remove_unknown_is_noinput(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["source", "remove", "ghost"])
        assert result.exit_code == output.EXIT_NOINPUT

    def test_remove_asks_and_aborts_on_no(self, runner, data_dir, tmp_path):
        self._register(data_dir, tmp_path, "notes")
        result = runner.invoke(
            cli_module.cli, ["source", "remove", "notes"], input="n\n"
        )
        assert result.exit_code != 0
        with PageDatabase(data_dir / "arciv.db") as db:
            assert db.get_source("notes") is not None

    def test_remove_force_skips_prompt(self, runner, data_dir, tmp_path):
        self._register(data_dir, tmp_path, "notes")
        result = runner.invoke(cli_module.cli, ["source", "remove", "notes", "--force"])
        assert result.exit_code == 0
        with PageDatabase(data_dir / "arciv.db") as db:
            assert db.get_source("notes") is None

    def test_remove_keeps_pages_by_default(self, runner, data_dir, tmp_path):
        self._register(data_dir, tmp_path, "notes")
        _seed(data_dir, [_page("https://example.com/a")])
        with PageDatabase(data_dir / "arciv.db") as db:
            db.replace_links_for_files(
                [],
                [("https://example.com/a", "note.md", "notes", "2026-06-01T00:00:00")],
            )
        result = runner.invoke(cli_module.cli, ["source", "remove", "notes", "--force"])
        assert result.exit_code == 0
        with PageDatabase(data_dir / "arciv.db") as db:
            assert db.get("https://example.com/a") is not None

    def test_remove_files_deletes_exclusive_pages_only(
        self, runner, data_dir, tmp_path
    ):
        self._register(data_dir, tmp_path, "notes")
        self._register(data_dir, tmp_path, "other")
        # /solo is linked only by notes; /shared is linked by notes and other.
        solo = _page("https://example.com/solo")
        shared = _page("https://example.com/shared")
        _seed(data_dir, [solo, shared])
        with PageDatabase(data_dir / "arciv.db") as db:
            db.replace_links_for_files(
                [],
                [
                    (
                        "https://example.com/solo",
                        "a.md",
                        "notes",
                        "2026-06-01T00:00:00",
                    ),
                    (
                        "https://example.com/shared",
                        "a.md",
                        "notes",
                        "2026-06-01T00:00:00",
                    ),
                    (
                        "https://example.com/shared",
                        "b.md",
                        "other",
                        "2026-06-01T00:00:00",
                    ),
                ],
            )
        for page in (solo, shared):
            folder = data_dir / "saved" / page.slug
            folder.mkdir(parents=True)
            (folder / "page.md").write_text("x", encoding="utf-8")

        result = runner.invoke(
            cli_module.cli, ["source", "remove", "notes", "--force", "--remove-files"]
        )
        assert result.exit_code == 0
        with PageDatabase(data_dir / "arciv.db") as db:
            assert db.get("https://example.com/solo") is None
            assert db.get("https://example.com/shared") is not None
        assert not (data_dir / "saved" / solo.slug).exists()
        assert (data_dir / "saved" / shared.slug).exists()


def _write_user_rules(data_dir, toml_text: str) -> None:
    """Write a user rules.toml at the path the CLI loads (see data_dir)."""
    (data_dir / "rules.toml").write_text(toml_text, encoding="utf-8")


_SKIP_RULE = """\
[[rule]]
name = "myskip"
type = "host"
match = "skip-me.example.com"
  [[rule.action]]
  type = "skip"
  reason = "nope"
"""

_REWRITE_RULE = """\
[[rule]]
name = "myrewrite"
type = "host"
match = "rewrite-me.example.com"
  [[rule.action]]
  type = "prepend"
  text = "https://mirror/"
"""


class TestRules:
    """`rules list` shows the active (user + default) rules."""

    def test_list_shows_default_rules(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["rules", "list"])
        assert result.exit_code == 0
        assert "youtube" in result.stdout
        assert "medium to freedium" in result.stdout

    def test_list_is_tab_separated_name_first(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["rules", "list"])
        row = next(
            line for line in result.stdout.splitlines() if line.startswith("youtube\t")
        ).split("\t")
        assert row[0] == "youtube"
        assert row[1] == "domain"
        assert row[2] == "youtube.com"
        assert "skip" in row[3]

    def test_list_includes_user_rules_first(self, runner, data_dir):
        _write_user_rules(data_dir, _SKIP_RULE)
        result = runner.invoke(cli_module.cli, ["rules", "list"])
        lines = result.stdout.splitlines()
        assert lines[0].startswith("myskip\t")

    def test_list_emits_jsonl(self, runner, data_dir):
        _write_user_rules(data_dir, _SKIP_RULE)
        result = runner.invoke(cli_module.cli, ["--json", "rules", "list"])
        records = [json.loads(line) for line in result.stdout.splitlines()]
        record = next(r for r in records if r["name"] == "myskip")
        assert record["type"] == "host"
        assert record["match"] == "skip-me.example.com"
        assert record["actions"][0]["type"] == "skip"


class TestRulesTest:
    """`rules test <url>` reports skip / rewrite / passthrough verdicts."""

    def test_skip_names_the_rule(self, runner, data_dir):
        _write_user_rules(data_dir, _SKIP_RULE)
        result = runner.invoke(
            cli_module.cli, ["rules", "test", "https://skip-me.example.com/post"]
        )
        assert result.exit_code == 0
        assert result.stdout.startswith("skipped:")
        assert "rule 'myskip'" in result.stdout

    def test_rewrite_shows_target_and_rule(self, runner, data_dir):
        _write_user_rules(data_dir, _REWRITE_RULE)
        result = runner.invoke(
            cli_module.cli, ["rules", "test", "https://rewrite-me.example.com/post"]
        )
        assert result.exit_code == 0
        assert (
            "rewritten -> https://mirror/https://rewrite-me.example.com/post"
            in result.stdout
        )
        assert "rule 'myrewrite'" in result.stdout

    def test_guard_skip_has_no_rule(self, runner, data_dir):
        # A media URL is skipped by an in-code guard, so no rule is named.
        result = runner.invoke(
            cli_module.cli, ["rules", "test", "https://example.com/photo.png"]
        )
        assert result.exit_code == 0
        assert result.stdout.startswith("skipped:")
        assert "rule" not in result.stdout

    def test_passthrough_when_no_rule_fires(self, runner, data_dir):
        result = runner.invoke(
            cli_module.cli, ["rules", "test", "https://unmatched.example.com/post"]
        )
        assert result.exit_code == 0
        assert result.stdout.startswith("passthrough:")
        assert "rule" not in result.stdout

    def test_json_emits_structured_verdict(self, runner, data_dir):
        _write_user_rules(data_dir, _SKIP_RULE)
        result = runner.invoke(
            cli_module.cli,
            ["--json", "rules", "test", "https://skip-me.example.com/post"],
        )
        assert result.exit_code == 0
        obj = json.loads(result.stdout)
        assert obj["verdict"] == "skipped"
        assert obj["rule"] == "myskip"
        assert obj["reason"] == "nope"


class TestGlobalOptions:
    """Global options must work both before and after the command."""

    def test_json_after_command(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["status", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output)["total"] == 0

    def test_json_before_command(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["--json", "status"])
        assert result.exit_code == 0
        assert json.loads(result.output)["total"] == 0

    def test_json_after_subgroup_command(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["db", "dir", "--json"])
        assert result.exit_code == 0
        assert result.output.strip() == str(data_dir)

    def test_quiet_after_command(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["status", "-q"])
        assert result.exit_code == 0

    def test_tokens_after_double_dash_are_not_hoisted(self, runner, data_dir):
        # "--" ends option parsing; a literal "--json" after it must stay a
        # positional argument (which status doesn't take), not become global.
        result = runner.invoke(cli_module.cli, ["status", "--", "--json"])
        assert result.exit_code != 0


class TestVersion:
    def test_version_prints_and_exits(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["--version"])
        assert result.exit_code == 0
        assert result.stdout.startswith("arciv ")


class TestPipelineJsonSummaries:
    """Mutating commands emit a {indexed, fetched, parsed, failed} object."""

    def test_fetch_emits_summary(self, runner, data_dir, monkeypatch):
        _seed(data_dir, [_page("https://example.com/a", fetched_at=None)])

        def fake_fetch_urls(db, urls, refetch=False):
            return [db.get(urls[0])] if urls else []

        monkeypatch.setattr(cli_module, "fetch_urls", fake_fetch_urls)
        result = runner.invoke(cli_module.cli, ["--json", "fetch"])
        assert result.exit_code == 0
        obj = json.loads(result.stdout)
        assert obj == {"indexed": 0, "fetched": 1, "parsed": 0, "failed": 0}

    def test_fetch_counts_failures(self, runner, data_dir, monkeypatch):
        _seed(data_dir, [_page("https://example.com/a", fetched_at=None)])

        def fake_fetch_urls(db, urls, refetch=False):
            # Simulate a failed fetch: mark the page and return nothing.
            page = db.get(urls[0])
            page.fail_reason = "timeout"
            db.upsert(page)
            return []

        monkeypatch.setattr(cli_module, "fetch_urls", fake_fetch_urls)
        result = runner.invoke(cli_module.cli, ["--json", "fetch"])
        obj = json.loads(result.stdout)
        assert obj["fetched"] == 0
        assert obj["failed"] == 1

    def test_parse_emits_summary(self, runner, data_dir, monkeypatch):
        _seed(data_dir, [_page("https://example.com/a")])  # fetched, unparsed

        monkeypatch.setattr(cli_module, "parse_pending", lambda db, reparse=False: 1)
        result = runner.invoke(cli_module.cli, ["--json", "parse"])
        assert result.exit_code == 0
        obj = json.loads(result.stdout)
        assert obj["parsed"] == 1
        assert obj["indexed"] == 0 and obj["fetched"] == 0

    def test_get_emits_summary(self, runner, data_dir, monkeypatch):
        monkeypatch.setattr(
            cli_module, "register_urls", lambda db, urls: ["https://a.com/1"]
        )
        monkeypatch.setattr(
            cli_module, "fetch_urls", lambda db, urls, refetch=False: []
        )
        monkeypatch.setattr(cli_module, "parse_pending", lambda db: 1)
        result = runner.invoke(cli_module.cli, ["--json", "get", "https://a.com/1"])
        assert result.exit_code == 0
        obj = json.loads(result.stdout)
        assert obj == {"indexed": 1, "fetched": 0, "parsed": 1, "failed": 0}

    def test_archive_source_emits_summary(
        self, runner, data_dir, tmp_path, monkeypatch
    ):
        notes = tmp_path / "notes"
        notes.mkdir()
        with PageDatabase(data_dir / "arciv.db") as db:
            db.add_source(Source("notes", str(notes), datetime.now(UTC).isoformat()))
        monkeypatch.setattr(
            cli_module,
            "archive_source",
            lambda db, name: ArchiveResult(
                urls=["https://a.com/1", "https://a.com/2"], fetched=[], parsed=2
            ),
        )
        result = runner.invoke(cli_module.cli, ["--json", "source", "update", "notes"])
        assert result.exit_code == 0
        obj = json.loads(result.stdout)
        assert obj["indexed"] == 2 and obj["parsed"] == 2


class TestStreams:
    def test_data_on_stdout_logs_on_stderr(self, runner, data_dir):
        # `source` with none registered logs a hint to stderr; stdout (data)
        # stays empty so pipes see only data.
        result = runner.invoke(cli_module.cli, ["source"])
        assert result.exit_code == 0
        assert result.stdout == ""
        assert "No sources registered" in result.stderr

    def test_quiet_suppresses_info_logs(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["-q", "source"])
        assert result.exit_code == 0
        assert result.stderr == ""


class TestJson:
    def test_status_emits_single_object(self, runner, data_dir):
        _seed(data_dir, [_page("https://example.com/a")])
        result = runner.invoke(cli_module.cli, ["--json", "status"])
        lines = result.stdout.splitlines()
        assert len(lines) == 1
        obj = json.loads(lines[0])
        assert obj["total"] == 1
        assert obj["failures"] == []

    def test_list_emits_jsonl(self, runner, data_dir):
        _seed(
            data_dir,
            [_page("https://example.com/new", fetched_at="2026-06-10T10:15:00+00:00")],
        )
        result = runner.invoke(cli_module.cli, ["--json", "list"])
        records = [json.loads(line) for line in result.stdout.splitlines()]
        assert records[0]["url"] == "https://example.com/new"
        assert records[0]["domain"] == "example.com"

    def test_sources_emits_jsonl(self, runner, data_dir):
        with PageDatabase(data_dir / "arciv.db") as db:
            db.add_source(Source("notes", "/tmp/notes", datetime.now(UTC).isoformat()))
        result = runner.invoke(cli_module.cli, ["--json", "source"])
        records = [json.loads(line) for line in result.stdout.splitlines()]
        assert records == [{"name": "notes", "path": "/tmp/notes"}]

    def test_path_emits_object(self, runner, data_dir):
        page = _page("https://example.com/post", parsed_at="2026-06-11T01:00:00+00:00")
        _seed(data_dir, [page])
        md_path = data_dir / "saved" / page.slug / "page.md"
        md_path.parent.mkdir(parents=True)
        md_path.write_text("# Hello\n", encoding="utf-8")
        result = runner.invoke(
            cli_module.cli, ["--json", "path", "https://example.com/post"]
        )
        obj = json.loads(result.stdout)
        assert obj == {"url": "https://example.com/post", "path": str(md_path)}


class TestNull:
    def test_null_separates_records_with_nul(self, runner, data_dir):
        _seed(
            data_dir,
            [
                _page("https://a.com/1", fetched_at="2026-06-10T00:00:00+00:00"),
                _page("https://a.com/2", fetched_at="2026-06-11T00:00:00+00:00"),
            ],
        )
        result = runner.invoke(cli_module.cli, ["list", "-n", "0", "--null"])
        assert result.exit_code == 0
        assert "\n" not in result.stdout
        records = [r for r in result.stdout.split("\0") if r]
        assert len(records) == 2


class TestStdin:
    def test_get_dash_reads_urls_from_stdin(self, runner, data_dir, monkeypatch):
        captured = {}

        def fake_register(db, urls):
            captured["urls"] = urls
            return []

        monkeypatch.setattr(cli_module, "register_urls", fake_register)
        result = runner.invoke(
            cli_module.cli, ["get", "-"], input="https://a.com\n\n  https://b.com  \n"
        )
        assert result.exit_code == 0
        assert captured["urls"] == ["https://a.com", "https://b.com"]


class TestExtract:
    NOTE = (
        "---\ntags: [reading]\n---\n"
        "A [post](https://example.com/post) worth keeping.\n"
        "Bare link: https://example.com/other\n"
        "Repeated: https://example.com/post\n"
    )

    def test_prints_deduped_urls_in_order(self, runner, data_dir, tmp_path):
        note = tmp_path / "note.md"
        note.write_text(self.NOTE, encoding="utf-8")
        result = runner.invoke(cli_module.cli, ["extract", str(note)])
        assert result.exit_code == 0
        assert result.output.splitlines() == [
            "https://example.com/post",
            "https://example.com/other",
        ]

    def test_touches_no_database(self, runner, data_dir, tmp_path):
        note = tmp_path / "note.md"
        note.write_text(self.NOTE, encoding="utf-8")
        result = runner.invoke(cli_module.cli, ["extract", str(note)])
        assert result.exit_code == 0
        assert not (data_dir / "arciv.db").exists()

    def test_dash_reads_text_from_stdin(self, runner, data_dir):
        result = runner.invoke(
            cli_module.cli,
            ["extract", "-"],
            input="see https://example.com/a and https://example.com/b\n",
        )
        assert result.exit_code == 0
        assert result.output.splitlines() == [
            "https://example.com/a",
            "https://example.com/b",
        ]

    def test_missing_file_is_noinput(self, runner, data_dir, tmp_path):
        result = runner.invoke(cli_module.cli, ["extract", str(tmp_path / "nope.md")])
        assert result.exit_code == output.EXIT_NOINPUT
        assert "Cannot read" in result.stderr

    def test_json_emits_jsonl(self, runner, data_dir, tmp_path):
        note = tmp_path / "note.md"
        note.write_text(self.NOTE, encoding="utf-8")
        result = runner.invoke(cli_module.cli, ["--json", "extract", str(note)])
        assert result.exit_code == 0
        records = [json.loads(line) for line in result.output.splitlines()]
        assert records == [
            {"url": "https://example.com/post"},
            {"url": "https://example.com/other"},
        ]

    def test_variadic_dedupes_across_files(self, runner, data_dir, tmp_path):
        a = tmp_path / "a.md"
        a.write_text("see https://example.com/a and https://example.com/x\n")
        b = tmp_path / "b.md"
        b.write_text("also https://example.com/b and https://example.com/x\n")
        result = runner.invoke(cli_module.cli, ["extract", str(a), str(b)])
        assert result.exit_code == 0
        assert result.output.splitlines() == [
            "https://example.com/a",
            "https://example.com/x",
            "https://example.com/b",
        ]

    def test_files_from_reads_paths_file(self, runner, data_dir, tmp_path):
        a = tmp_path / "a.md"
        a.write_text("https://example.com/a\n")
        b = tmp_path / "b.md"
        b.write_text("https://example.com/b\n")
        listing = tmp_path / "notes.txt"
        listing.write_text(f"{a}\n\n{b}\n")
        result = runner.invoke(cli_module.cli, ["extract", "-f", str(listing)])
        assert result.exit_code == 0
        assert result.output.splitlines() == [
            "https://example.com/a",
            "https://example.com/b",
        ]

    def test_files_from_dash_reads_paths_from_stdin(self, runner, data_dir, tmp_path):
        a = tmp_path / "a.md"
        a.write_text("https://example.com/a\n")
        b = tmp_path / "b.md"
        b.write_text("https://example.com/b\n")
        result = runner.invoke(
            cli_module.cli, ["extract", "-f", "-"], input=f"{a}\n{b}\n"
        )
        assert result.exit_code == 0
        assert result.output.splitlines() == [
            "https://example.com/a",
            "https://example.com/b",
        ]

    def test_positional_plus_files_from_dash(self, runner, data_dir, tmp_path):
        a = tmp_path / "a.md"
        a.write_text("https://example.com/a\n")
        b = tmp_path / "b.md"
        b.write_text("https://example.com/b\n")
        result = runner.invoke(
            cli_module.cli, ["extract", str(a), "-f", "-"], input=f"{b}\n"
        )
        assert result.exit_code == 0
        assert result.output.splitlines() == [
            "https://example.com/a",
            "https://example.com/b",
        ]

    def test_stdin_conflict_errors(self, runner, data_dir):
        result = runner.invoke(
            cli_module.cli, ["extract", "-", "-f", "-"], input="whatever\n"
        )
        assert result.exit_code != 0

    def test_tty_guard_errors(self, runner, data_dir, monkeypatch):
        import types

        # Replace the module's ``sys`` reference so the runner re-swapping the
        # real ``sys.stdin`` during invoke does not clobber our isatty stub.
        fake_stdin = types.SimpleNamespace(isatty=lambda: True, read=lambda: "")
        fake_sys = types.SimpleNamespace(stdin=fake_stdin)
        monkeypatch.setattr(cli_module, "sys", fake_sys)
        result = runner.invoke(cli_module.cli, ["extract", "-"])
        assert result.exit_code != 0
        assert "Cannot read from stdin" in result.output

    def test_partial_failure_prints_and_exits_noinput(self, runner, data_dir, tmp_path):
        good = tmp_path / "good.md"
        good.write_text("https://example.com/good\n")
        missing = tmp_path / "nope.md"
        result = runner.invoke(cli_module.cli, ["extract", str(good), str(missing)])
        assert result.exit_code == output.EXIT_NOINPUT
        assert "https://example.com/good" in result.output.splitlines()
        assert "Cannot read" in result.stderr


class TestGetNoSave:
    def test_prints_links_and_touches_nothing(self, runner, data_dir, monkeypatch):
        captured = {}

        def fake_fetch_links(url, page_timeout):
            captured["url"] = url
            return ["https://book.example.com/ch1", "https://book.example.com/ch2"]

        monkeypatch.setattr(cli_module, "fetch_links", fake_fetch_links)
        result = runner.invoke(
            cli_module.cli, ["get", "https://book.example.com/toc", "--no-save"]
        )
        assert result.exit_code == 0
        assert captured["url"] == "https://book.example.com/toc"
        # The link count is logged to stderr; stdout carries only the links
        assert result.stdout.splitlines() == [
            "https://book.example.com/ch1",
            "https://book.example.com/ch2",
        ]
        assert not (data_dir / "arciv.db").exists()
        assert not (data_dir / "saved").exists()

    def test_json_emits_jsonl(self, runner, data_dir, monkeypatch):
        monkeypatch.setattr(
            cli_module, "fetch_links", lambda url, page_timeout: ["https://a.com/x"]
        )
        result = runner.invoke(
            cli_module.cli, ["--json", "get", "https://b.com/toc", "--no-save"]
        )
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"url": "https://a.com/x"}

    def test_url_rules_still_apply(self, runner, data_dir):
        # Non-HTTPS is skipped by the same processing a plain get uses
        result = runner.invoke(
            cli_module.cli, ["get", "http://example.com/toc", "--no-save"]
        )
        assert result.exit_code == output.EXIT_NOINPUT
        assert "Skipped" in result.stderr

    def test_pdf_url_is_an_error(self, runner, data_dir):
        result = runner.invoke(
            cli_module.cli, ["get", "https://arxiv.org/pdf/2305.14406", "--no-save"]
        )
        assert result.exit_code == 1
        assert "PDF" in result.stderr

    def test_fetch_failure_is_reported(self, runner, data_dir, monkeypatch):
        def failing(url, page_timeout):
            raise cli_module.LinkFetchError("DNS resolution failed")

        monkeypatch.setattr(cli_module, "fetch_links", failing)
        result = runner.invoke(
            cli_module.cli, ["get", "https://gone.example.com/", "--no-save"]
        )
        assert result.exit_code == 1
        assert "DNS resolution failed" in result.stderr

    def test_requires_a_url_target(self, runner, data_dir, tmp_path):
        note = tmp_path / "note.md"
        note.write_text("x", encoding="utf-8")
        result = runner.invoke(
            cli_module.cli, ["get", "--file", str(note), "--no-save"]
        )
        assert result.exit_code == output.EXIT_USAGE

    def test_stdin_target_is_usage_error(self, runner, data_dir):
        result = runner.invoke(
            cli_module.cli, ["get", "-", "--no-save"], input="https://a.com\n"
        )
        assert result.exit_code == output.EXIT_USAGE

    def test_refetch_is_usage_error(self, runner, data_dir):
        result = runner.invoke(
            cli_module.cli, ["get", "https://a.com/x", "--no-save", "--refetch"]
        )
        assert result.exit_code == output.EXIT_USAGE


class TestExitCodes:
    def test_unknown_url_is_noinput(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["path", "https://example.com/nope"])
        assert result.exit_code == output.EXIT_NOINPUT
        assert "Unknown URL" in result.stderr

    def test_missing_source_is_noinput(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["source", "remove", "ghost"])
        assert result.exit_code == output.EXIT_NOINPUT

    def test_get_without_target_is_usage(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["get"])
        assert result.exit_code == output.EXIT_USAGE

    def test_index_source_and_all_is_usage(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["index", "notes", "--all"])
        assert result.exit_code == output.EXIT_USAGE


class TestLogging:
    def test_logs_go_to_stderr_not_stdout(self, capfd):
        # Data commands print to stdout; logs are diagnostics and must go
        # to stderr so output like `arciv list` stays clean and pipeable.
        configure_logger(log_file=False)
        try:
            logger.info("STDERR-MARKER")
        finally:
            logger.remove()  # flush and join the enqueue worker
        out, err = capfd.readouterr()
        assert "STDERR-MARKER" not in out
        assert "STDERR-MARKER" in err
