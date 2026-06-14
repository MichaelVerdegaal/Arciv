"""Tests for the CLI: command parity, stdout/stderr split, JSON, exit codes."""

import json
import sys
from datetime import datetime, timezone

import pytest
from loguru import logger
from typer.testing import CliRunner

import arciv.scripts.cli as cli_module
from arciv.db import Page, PageDatabase, Source
from arciv.scrape import slug_for_url
from arciv.scripts import output
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
        result = runner.invoke(cli_module.cli, ["list", "--n", "1"])
        assert result.exit_code == 0
        assert result.output.splitlines() == [
            "2026-06-10T10:15:00\texample.com\thttps://example.com/new"
        ]

    def test_n_zero_shows_everything(self, runner, data_dir):
        self._seed_three(data_dir)
        result = runner.invoke(cli_module.cli, ["list", "--n", "0"])
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
        result = runner.invoke(cli_module.cli, ["list", "--n", "0", "--null"])
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
