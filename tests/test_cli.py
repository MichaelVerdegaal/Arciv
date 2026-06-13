"""Tests for the cyclopts CLI: parity, stdout/stderr split, exit codes.

cyclopts has no ``CliRunner``; the CLI is driven through ``main()`` with
a patched ``sys.argv`` (the real entry path, so exit codes and the global
``--json`` flag are covered too). Output is captured at the file-descriptor
level (``capfd``) so loguru's stderr sink and NUL bytes are seen faithfully.
"""

import json
import sys

import pytest
from loguru import logger

import arciv.scripts.cli as cli_module
from arciv.db import Page, PageDatabase
from arciv.scripts import output


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Point the CLI at a temp data dir with a deterministic logger.

    The logger sink is synchronous (no enqueue) and writes only the
    message to stderr, so stdout/stderr assertions are stable.
    """

    def fake_configure(level: str = "INFO", color: str = "auto") -> None:
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


def run(monkeypatch, *argv: str) -> int:
    """Invoke the CLI as if from the shell; return the exit code."""
    monkeypatch.setattr(sys, "argv", ["arciv", *argv])
    return cli_module.main()


def _page(url: str, **overrides) -> Page:
    defaults = dict(
        original_url=url,
        domain="example.com",
        slug="example.com-abc12345",
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


class TestStreams:
    def test_data_on_stdout_logs_on_stderr(self, monkeypatch, data_dir, capfd):
        # `sources` with no sources logs a hint; data stays on stdout
        _seed(data_dir, [_page("https://example.com/a")])
        code = run(monkeypatch, "sources")
        out, err = capfd.readouterr()
        assert code == output.EXIT_OK
        assert out == ""  # no registered sources -> no data
        assert "No sources registered" in err

    def test_quiet_suppresses_info_logs(self, monkeypatch, data_dir, capfd):
        code = run(monkeypatch, "-q", "sources")
        _, err = capfd.readouterr()
        assert code == output.EXIT_OK
        assert err == ""


class TestList:
    def _seed_three(self, data_dir):
        _seed(
            data_dir,
            [
                _page(
                    "https://example.com/old", fetched_at="2026-06-01T08:00:00+00:00"
                ),
                _page(
                    "https://example.com/mid", fetched_at="2026-06-05T09:30:00+00:00"
                ),
                _page(
                    "https://example.com/new", fetched_at="2026-06-10T10:15:00+00:00"
                ),
                _page("https://example.com/pending", fetched_at=None),
            ],
        )

    def test_rows_are_tab_separated_newest_first(self, monkeypatch, data_dir, capfd):
        self._seed_three(data_dir)
        code = run(monkeypatch, "list")
        out, _ = capfd.readouterr()
        lines = out.splitlines()
        assert code == 0
        assert lines[0] == "2026-06-10T10:15:00\texample.com\thttps://example.com/new"
        assert [line.split("\t")[2] for line in lines] == [
            "https://example.com/new",
            "https://example.com/mid",
            "https://example.com/old",
        ]

    def test_n_limits_rows(self, monkeypatch, data_dir, capfd):
        self._seed_three(data_dir)
        run(monkeypatch, "list", "--n", "1")
        out, _ = capfd.readouterr()
        assert out.splitlines() == [
            "2026-06-10T10:15:00\texample.com\thttps://example.com/new"
        ]

    def test_n_zero_shows_everything(self, monkeypatch, data_dir, capfd):
        self._seed_three(data_dir)
        run(monkeypatch, "list", "--n", "0")
        out, _ = capfd.readouterr()
        assert len(out.splitlines()) == 3

    def test_negative_n_is_usage_error(self, monkeypatch, data_dir, capfd):
        code = run(monkeypatch, "list", "--n", "-1")
        assert code == output.EXIT_USAGE

    def test_reverse_shows_oldest_first(self, monkeypatch, data_dir, capfd):
        self._seed_three(data_dir)
        run(monkeypatch, "list", "--reverse")
        out, _ = capfd.readouterr()
        urls = [line.split("\t")[2] for line in out.splitlines()]
        assert urls[0] == "https://example.com/old"
        assert urls[-1] == "https://example.com/new"

    def test_empty_archive_prints_nothing(self, monkeypatch, data_dir, capfd):
        code = run(monkeypatch, "list")
        out, _ = capfd.readouterr()
        assert code == 0
        assert out == ""

    def test_domain_filters_to_one_domain(self, monkeypatch, data_dir, capfd):
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
        run(monkeypatch, "list", "--domain", "a.com")
        out, _ = capfd.readouterr()
        urls = [line.split("\t")[2] for line in out.splitlines()]
        assert urls == ["https://a.com/2", "https://a.com/1"]

    def test_json_emits_valid_jsonl(self, monkeypatch, data_dir, capfd):
        self._seed_three(data_dir)
        run(monkeypatch, "--json", "list")
        out, _ = capfd.readouterr()
        records = [json.loads(line) for line in out.splitlines()]
        assert [r["url"] for r in records] == [
            "https://example.com/new",
            "https://example.com/mid",
            "https://example.com/old",
        ]
        assert records[0]["domain"] == "example.com"

    def test_null_separates_records_with_nul(self, monkeypatch, data_dir, capfdbinary):
        self._seed_three(data_dir)
        run(monkeypatch, "list", "--n", "0", "--null")
        out, _ = capfdbinary.readouterr()
        assert b"\n" not in out
        records = [r for r in out.split(b"\0") if r]
        assert len(records) == 3


class TestStatus:
    def test_text_counts(self, monkeypatch, data_dir, capfd):
        _seed(data_dir, [_page("https://example.com/a")])
        code = run(monkeypatch, "status")
        out, _ = capfd.readouterr()
        assert code == 0
        assert "Pages: 1 total" in out
        assert "Recent fetches" not in out

    def test_json_is_single_object(self, monkeypatch, data_dir, capfd):
        _seed(data_dir, [_page("https://example.com/a")])
        run(monkeypatch, "--json", "status")
        out, _ = capfd.readouterr()
        lines = out.splitlines()
        assert len(lines) == 1
        obj = json.loads(lines[0])
        assert obj["total"] == 1
        assert obj["failures"] == []


class TestPath:
    def _seed_parsed(self, data_dir):
        page = _page("https://example.com/post", parsed_at="2026-06-11T01:00:00+00:00")
        _seed(data_dir, [page])
        md_path = data_dir / "saved" / page.slug / "page.md"
        md_path.parent.mkdir(parents=True)
        md_path.write_text("# Hello\n", encoding="utf-8")
        return md_path

    def test_prints_markdown_filepath(self, monkeypatch, data_dir, capfd):
        md_path = self._seed_parsed(data_dir)
        code = run(monkeypatch, "path", "https://example.com/post")
        out, _ = capfd.readouterr()
        assert code == 0
        assert out.strip() == str(md_path)

    def test_json_emits_url_and_path(self, monkeypatch, data_dir, capfd):
        md_path = self._seed_parsed(data_dir)
        run(monkeypatch, "--json", "path", "https://example.com/post")
        out, _ = capfd.readouterr()
        obj = json.loads(out)
        assert obj == {"url": "https://example.com/post", "path": str(md_path)}

    def test_url_is_normalized_for_lookup(self, monkeypatch, data_dir, capfd):
        md_path = self._seed_parsed(data_dir)
        code = run(monkeypatch, "path", "https://example.com/post#section-2")
        out, _ = capfd.readouterr()
        assert code == 0
        assert out.strip() == str(md_path)

    def test_unknown_url_exits_noinput(self, monkeypatch, data_dir, capfd):
        code = run(monkeypatch, "path", "https://example.com/nope")
        _, err = capfd.readouterr()
        assert code == output.EXIT_NOINPUT
        assert "Unknown URL" in err

    def test_pending_url_fails_with_hint(self, monkeypatch, data_dir, capfd):
        _seed(data_dir, [_page("https://example.com/post", fetched_at=None)])
        code = run(monkeypatch, "path", "https://example.com/post")
        _, err = capfd.readouterr()
        assert code != 0
        assert "arciv fetch" in err

    def test_unparsed_url_fails_with_hint(self, monkeypatch, data_dir, capfd):
        _seed(data_dir, [_page("https://example.com/post")])
        code = run(monkeypatch, "path", "https://example.com/post")
        _, err = capfd.readouterr()
        assert code != 0
        assert "arciv parse" in err

    def test_missing_file_on_disk_fails(self, monkeypatch, data_dir, capfd):
        _seed(
            data_dir,
            [_page("https://example.com/post", parsed_at="2026-06-11T01:00:00+00:00")],
        )
        code = run(monkeypatch, "path", "https://example.com/post")
        _, err = capfd.readouterr()
        assert code != 0
        assert "missing" in err


class TestGet:
    def test_no_target_is_usage_error(self, monkeypatch, data_dir, capfd):
        code = run(monkeypatch, "get")
        assert code == output.EXIT_USAGE

    def test_multiple_targets_is_usage_error(
        self, monkeypatch, data_dir, tmp_path, capfd
    ):
        f = tmp_path / "note.md"
        f.write_text("x", encoding="utf-8")
        code = run(monkeypatch, "get", "https://example.com", "--file", str(f))
        assert code == output.EXIT_USAGE

    def test_reads_urls_from_stdin(self, monkeypatch, data_dir, capfd):
        captured = {}

        def fake_register(db, urls):
            captured["urls"] = urls
            return []

        monkeypatch.setattr(cli_module, "register_urls", fake_register)
        monkeypatch.setattr(
            sys, "stdin", _FakeStdin("https://a.com\n\n  https://b.com  \n")
        )
        run(monkeypatch, "get", "-")
        assert captured["urls"] == ["https://a.com", "https://b.com"]


class TestIndex:
    def test_neither_source_nor_all_is_usage_error(self, monkeypatch, data_dir, capfd):
        code = run(monkeypatch, "index")
        assert code == output.EXIT_USAGE

    def test_both_source_and_all_is_usage_error(self, monkeypatch, data_dir, capfd):
        code = run(monkeypatch, "index", "notes", "--all")
        assert code == output.EXIT_USAGE


class TestSources:
    def test_json_emits_jsonl_per_source(self, monkeypatch, data_dir, capfd):
        from datetime import datetime, timezone
        from arciv.db import Source

        with PageDatabase(data_dir / "arciv.db") as db:
            db.add_source(
                Source("notes", "/tmp/notes", datetime.now(timezone.utc).isoformat())
            )
        run(monkeypatch, "--json", "sources")
        out, _ = capfd.readouterr()
        records = [json.loads(line) for line in out.splitlines()]
        assert records == [{"name": "notes", "path": "/tmp/notes"}]


class TestDbGroup:
    def test_dir_prints_data_dir(self, monkeypatch, data_dir, capfd):
        code = run(monkeypatch, "db", "dir")
        out, _ = capfd.readouterr()
        assert code == 0
        assert out.strip() == str(data_dir)

    def test_remove_force_deletes_db_and_sidecars(self, monkeypatch, data_dir, capfd):
        _seed(data_dir, [_page("https://example.com/a")])
        for suffix in ("-wal", "-shm"):
            (data_dir / f"arciv.db{suffix}").touch()
        code = run(monkeypatch, "db", "remove", "--force")
        assert code == 0
        assert not (data_dir / "arciv.db").exists()
        assert not (data_dir / "arciv.db-wal").exists()
        assert not (data_dir / "arciv.db-shm").exists()

    def test_remove_non_tty_without_force_refuses(self, monkeypatch, data_dir, capfd):
        _seed(data_dir, [_page("https://example.com/a")])
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        code = run(monkeypatch, "db", "remove")
        assert code == output.EXIT_USAGE
        assert (data_dir / "arciv.db").exists()

    def test_remove_declined_keeps_db(self, monkeypatch, data_dir, capfd):
        _seed(data_dir, [_page("https://example.com/a")])
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda prompt="": "n")
        code = run(monkeypatch, "db", "remove")
        assert code != 0
        assert (data_dir / "arciv.db").exists()

    def test_remove_confirmed_deletes_db(self, monkeypatch, data_dir, capfd):
        _seed(data_dir, [_page("https://example.com/a")])
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda prompt="": "y")
        code = run(monkeypatch, "db", "remove")
        assert code == 0
        assert not (data_dir / "arciv.db").exists()

    def test_remove_without_db_is_graceful(self, monkeypatch, data_dir, capfd):
        code = run(monkeypatch, "db", "remove")
        _, err = capfd.readouterr()
        assert code == 0
        assert "No database" in err


class TestParsing:
    def test_end_of_options_delimiter(self, monkeypatch, data_dir, capfd):
        # `--` should not break a normal invocation; the command still runs
        code = run(monkeypatch, "list", "--n", "5", "--")
        assert code == 0

    def test_keyboard_interrupt_returns_130(self, monkeypatch, capfd):
        class FakeApp:
            def meta(self):
                raise KeyboardInterrupt()

        monkeypatch.setattr(cli_module, "app", FakeApp())
        assert cli_module.main() == 130
        _, err = capfd.readouterr()
        assert "Aborted" in err


class _FakeStdin:
    """Minimal stdin stand-in: iterable lines plus isatty()."""

    def __init__(self, text: str) -> None:
        self._lines = text.splitlines(keepends=True)

    def __iter__(self):
        return iter(self._lines)

    def isatty(self) -> bool:
        return False
