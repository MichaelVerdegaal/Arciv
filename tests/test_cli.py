"""Tests for the CLI: command parity, stdout/stderr split, JSON, exit codes."""

import json
import sys
from datetime import datetime, timezone

import pytest
from loguru import logger
from typer.testing import CliRunner

import arciv.cli.cli as cli_module
from arciv.core.db import Page, PageDatabase, Rule, Source
from arciv.core.fetch import slug_for_url
from arciv.core.pipeline import ArchiveResult
from arciv.cli import output
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
            assert {p.url for p in db.get_all()} == {"https://example.com/ok"}
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
            assert len(db.get_all()) == 2

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


class TestAddAndArchive:
    """`add` archives after registering; `archive` re-archives a source.

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
        result = runner.invoke(cli_module.cli, ["add", str(notes), "notes"])
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
            cli_module.cli, ["add", str(notes), "notes", "--no-archive"]
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
        runner.invoke(cli_module.cli, ["add", str(notes), "notes", "--no-archive"])
        result = runner.invoke(
            cli_module.cli, ["add", str(notes), "notes", "--no-archive"]
        )
        assert result.exit_code != 0
        assert "already exists" in result.output

    def test_archive_source_invokes_pipeline(
        self, runner, data_dir, tmp_path, monkeypatch
    ):
        notes = tmp_path / "notes"
        notes.mkdir()
        with PageDatabase(data_dir / "arciv.db") as db:
            db.add_source(
                Source("notes", str(notes), datetime.now(timezone.utc).isoformat())
            )
        called = {}

        def fake_archive_source(db, name):
            called["name"] = name
            return ArchiveResult(urls=["https://a.com/1"], fetched=[], parsed=1)

        monkeypatch.setattr(cli_module, "archive_source", fake_archive_source)
        result = runner.invoke(cli_module.cli, ["archive", "notes"])
        assert result.exit_code == 0
        assert called["name"] == "notes"

    def test_archive_all_batches_every_source(
        self, runner, data_dir, tmp_path, monkeypatch
    ):
        notes = tmp_path / "notes"
        notes.mkdir()
        with PageDatabase(data_dir / "arciv.db") as db:
            db.add_source(
                Source("notes", str(notes), datetime.now(timezone.utc).isoformat())
            )
        captured = {}
        monkeypatch.setattr(cli_module, "index_all", lambda db: ["https://a.com/1"])

        def fake_archive_urls(db, urls):
            captured["urls"] = urls
            return ArchiveResult(urls=urls, fetched=[], parsed=0)

        monkeypatch.setattr(cli_module, "archive_urls", fake_archive_urls)
        result = runner.invoke(cli_module.cli, ["archive", "--all"])
        assert result.exit_code == 0
        assert captured["urls"] == ["https://a.com/1"]

    def test_archive_all_with_no_sources_is_graceful(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["archive", "--all"])
        assert result.exit_code == 0
        assert "No sources registered" in result.output

    def test_archive_unknown_source_is_noinput(self, runner, data_dir):
        # No source registered: the real archive_source raises KeyError before
        # any fetch, so no browser is launched.
        result = runner.invoke(cli_module.cli, ["archive", "ghost"])
        assert result.exit_code == output.EXIT_NOINPUT

    def test_archive_name_and_all_is_usage(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["archive", "notes", "--all"])
        assert result.exit_code == output.EXIT_USAGE


class TestRules:
    """`rules list/add/remove` give the CLI parity with the web rule view.

    A fresh database is seeded with built-in default rules, so these tests
    target a distinctive pattern of their own rather than asserting on the
    whole (defaulted) table.
    """

    PATTERN = "cli-test.example.com"

    def _added_rule(self, data_dir):
        with PageDatabase(data_dir / "arciv.db") as db:
            matches = [r for r in db.list_rules() if r.pattern == self.PATTERN]
        return matches

    def test_add_inserts_rule_at_the_end(self, runner, data_dir):
        result = runner.invoke(
            cli_module.cli, ["rules", "add", "domain", self.PATTERN, "skip"]
        )
        assert result.exit_code == 0
        matches = self._added_rule(data_dir)
        assert len(matches) == 1
        assert matches[0].match_type == "domain"
        assert matches[0].action == "skip"
        # Appended, never reordering the seeded defaults.
        with PageDatabase(data_dir / "arciv.db") as db:
            assert db.list_rules()[-1].pattern == self.PATTERN

    def test_add_rewrite_with_replacement(self, runner, data_dir):
        result = runner.invoke(
            cli_module.cli,
            ["rules", "add", "domain", self.PATTERN, "rewrite", "-r", "scribe.rip"],
        )
        assert result.exit_code == 0
        matches = self._added_rule(data_dir)
        assert matches[0].action == "rewrite"
        assert matches[0].replacement == "scribe.rip"

    def test_add_rewrite_without_replacement_is_usage(self, runner, data_dir):
        result = runner.invoke(
            cli_module.cli, ["rules", "add", "domain", self.PATTERN, "rewrite"]
        )
        assert result.exit_code == output.EXIT_USAGE
        assert "replacement" in result.output
        assert self._added_rule(data_dir) == []

    def test_add_unknown_match_type_is_usage(self, runner, data_dir):
        result = runner.invoke(
            cli_module.cli, ["rules", "add", "bogus", self.PATTERN, "skip"]
        )
        assert result.exit_code == output.EXIT_USAGE
        assert "match type" in result.output

    def test_add_unknown_action_is_usage(self, runner, data_dir):
        result = runner.invoke(
            cli_module.cli, ["rules", "add", "domain", self.PATTERN, "bogus"]
        )
        assert result.exit_code == output.EXIT_USAGE
        assert "action" in result.output

    def test_list_is_tab_separated_with_id_first(self, runner, data_dir):
        with PageDatabase(data_dir / "arciv.db") as db:
            rule = db.add_rule(
                Rule(match_type="domain", pattern=self.PATTERN, action="skip")
            )
        result = runner.invoke(cli_module.cli, ["rules", "list"])
        assert result.exit_code == 0
        row = next(
            line for line in result.stdout.splitlines() if self.PATTERN in line
        ).split("\t")
        assert row == [str(rule.id), "domain", self.PATTERN, "skip", ""]

    def test_list_emits_jsonl(self, runner, data_dir):
        with PageDatabase(data_dir / "arciv.db") as db:
            rule = db.add_rule(
                Rule(
                    match_type="domain",
                    pattern=self.PATTERN,
                    action="rewrite",
                    replacement="scribe.rip",
                )
            )
        result = runner.invoke(cli_module.cli, ["--json", "rules", "list"])
        records = [json.loads(line) for line in result.stdout.splitlines()]
        record = next(r for r in records if r["pattern"] == self.PATTERN)
        assert record["replacement"] == "scribe.rip"
        assert record["id"] == rule.id

    def test_remove_deletes_rule(self, runner, data_dir):
        with PageDatabase(data_dir / "arciv.db") as db:
            rule = db.add_rule(
                Rule(match_type="domain", pattern=self.PATTERN, action="skip")
            )
        result = runner.invoke(cli_module.cli, ["rules", "remove", str(rule.id)])
        assert result.exit_code == 0
        assert self._added_rule(data_dir) == []

    def test_remove_unknown_id_is_noinput(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["rules", "remove", "999999"])
        assert result.exit_code == output.EXIT_NOINPUT


class TestRulesTest:
    """`rules test <url>` reports skip / rewrite / passthrough verdicts."""

    def test_skip_names_the_rule(self, runner, data_dir):
        with PageDatabase(data_dir / "arciv.db") as db:
            rule = db.add_rule(
                Rule(match_type="host", pattern="skip-me.example.com", action="skip")
            )
        result = runner.invoke(
            cli_module.cli, ["rules", "test", "https://skip-me.example.com/post"]
        )
        assert result.exit_code == 0
        assert result.stdout.startswith("skipped:")
        assert f"rule {rule.id}" in result.stdout

    def test_rewrite_shows_target_and_rule(self, runner, data_dir):
        with PageDatabase(data_dir / "arciv.db") as db:
            rule = db.add_rule(
                Rule(
                    match_type="host",
                    pattern="rewrite-me.example.com",
                    action="rewrite",
                    replacement="scribe.rip",
                )
            )
        result = runner.invoke(
            cli_module.cli, ["rules", "test", "https://rewrite-me.example.com/post"]
        )
        assert result.exit_code == 0
        assert "rewritten -> https://scribe.rip/post" in result.stdout
        assert f"rule {rule.id}" in result.stdout

    def test_passthrough_when_no_rule_fires(self, runner, data_dir):
        result = runner.invoke(
            cli_module.cli, ["rules", "test", "https://unmatched.example.com/post"]
        )
        assert result.exit_code == 0
        assert result.stdout.startswith("passthrough:")
        assert "rule" not in result.stdout

    def test_json_emits_structured_verdict(self, runner, data_dir):
        with PageDatabase(data_dir / "arciv.db") as db:
            rule = db.add_rule(
                Rule(match_type="host", pattern="skip-me.example.com", action="skip")
            )
        result = runner.invoke(
            cli_module.cli,
            ["--json", "rules", "test", "https://skip-me.example.com/post"],
        )
        assert result.exit_code == 0
        obj = json.loads(result.stdout)
        assert obj["verdict"] == "skipped"
        assert obj["rule_id"] == rule.id
        assert obj["reason"]


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
            db.add_source(
                Source("notes", str(notes), datetime.now(timezone.utc).isoformat())
            )
        monkeypatch.setattr(
            cli_module,
            "archive_source",
            lambda db, name: ArchiveResult(
                urls=["https://a.com/1", "https://a.com/2"], fetched=[], parsed=2
            ),
        )
        result = runner.invoke(cli_module.cli, ["--json", "archive", "notes"])
        assert result.exit_code == 0
        obj = json.loads(result.stdout)
        assert obj["indexed"] == 2 and obj["parsed"] == 2


class TestStreams:
    def test_data_on_stdout_logs_on_stderr(self, runner, data_dir):
        # `sources` with none registered logs a hint to stderr; stdout (data)
        # stays empty so pipes see only data.
        result = runner.invoke(cli_module.cli, ["sources"])
        assert result.exit_code == 0
        assert result.stdout == ""
        assert "No sources registered" in result.stderr

    def test_quiet_suppresses_info_logs(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["-q", "sources"])
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
            db.add_source(
                Source("notes", "/tmp/notes", datetime.now(timezone.utc).isoformat())
            )
        result = runner.invoke(cli_module.cli, ["--json", "sources"])
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


class TestExitCodes:
    def test_unknown_url_is_noinput(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["path", "https://example.com/nope"])
        assert result.exit_code == output.EXIT_NOINPUT
        assert "Unknown URL" in result.stderr

    def test_missing_source_is_noinput(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["remove", "ghost"])
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
