"""Tests for the inspection/data-dir CLI commands (list, path, status, db)."""

import pytest
from click.testing import CliRunner

import arciv.scripts.cli as cli_module
from arciv.db import Page, PageDatabase


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Point the CLI at a temp data dir and silence the logger setup."""
    monkeypatch.setattr(cli_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cli_module, "DB_PATH", tmp_path / "arciv.db")
    monkeypatch.setattr(cli_module, "SAVED_DIR", tmp_path / "saved")
    monkeypatch.setattr(cli_module, "configure_logger", lambda: None)
    return tmp_path


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

    def test_first_line_is_header(self, runner, data_dir):
        self._seed_three(data_dir)
        result = runner.invoke(cli_module.cli, ["list"])
        assert result.exit_code == 0
        assert result.output.splitlines()[0] == "fetched_at\tdomain\turl\tfilepath"

    def test_rows_are_tab_separated_newest_first(self, runner, data_dir):
        self._seed_three(data_dir)
        result = runner.invoke(cli_module.cli, ["list"])
        assert result.exit_code == 0
        rows = result.output.splitlines()[1:]  # skip header
        # Unparsed pages have a trailing empty filepath column
        assert rows[0] == "2026-06-10T10:15:00\texample.com\thttps://example.com/new\t"
        assert [line.split("\t")[2] for line in rows] == [
            "https://example.com/new",
            "https://example.com/mid",
            "https://example.com/old",
        ]

    def test_n_limits_rows(self, runner, data_dir):
        self._seed_three(data_dir)
        result = runner.invoke(cli_module.cli, ["list", "--n", "1"])
        assert result.exit_code == 0
        assert result.output.splitlines()[1:] == [
            "2026-06-10T10:15:00\texample.com\thttps://example.com/new\t"
        ]

    def test_n_zero_shows_everything(self, runner, data_dir):
        self._seed_three(data_dir)
        result = runner.invoke(cli_module.cli, ["list", "--n", "0"])
        assert len(result.output.splitlines()[1:]) == 3

    def test_reverse_shows_oldest_first(self, runner, data_dir):
        self._seed_three(data_dir)
        result = runner.invoke(cli_module.cli, ["list", "--reverse"])
        first_urls = [line.split("\t")[2] for line in result.output.splitlines()[1:]]
        assert first_urls[0] == "https://example.com/old"
        assert first_urls[-1] == "https://example.com/new"

    def test_empty_archive_prints_nothing(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["list"])
        assert result.exit_code == 0
        assert result.output == ""

    def test_no_header_omits_header(self, runner, data_dir):
        self._seed_three(data_dir)
        result = runner.invoke(cli_module.cli, ["list", "--no-header"])
        assert result.exit_code == 0
        assert result.output.splitlines()[0].startswith("2026-06-10T10:15:00\t")

    def test_filepath_column_holds_markdown_path_when_parsed(self, runner, data_dir):
        page = _page("https://example.com/post", parsed_at="2026-06-11T01:00:00+00:00")
        _seed(data_dir, [page])
        md_path = data_dir / "saved" / page.slug / "page.md"
        md_path.parent.mkdir(parents=True)
        md_path.write_text("# Hi\n", encoding="utf-8")
        result = runner.invoke(cli_module.cli, ["list"])
        assert result.exit_code == 0
        assert result.output.splitlines()[1].split("\t")[3] == str(md_path)

    def test_filepath_column_empty_when_not_parsed(self, runner, data_dir):
        # Fetched but not parsed: no markdown on disk, so the column is blank
        _seed(data_dir, [_page("https://example.com/post")])
        result = runner.invoke(cli_module.cli, ["list"])
        assert result.exit_code == 0
        assert result.output.splitlines()[1].split("\t")[3] == ""

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
        urls = [line.split("\t")[2] for line in result.output.splitlines()[1:]]
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


class TestIndexCli:
    def test_source_name_echoes_indexed_urls(self, runner, data_dir, monkeypatch):
        monkeypatch.setattr(
            cli_module, "index_source", lambda db, name: ["https://a/1", "https://a/2"]
        )
        result = runner.invoke(cli_module.cli, ["index", "notes"])
        assert result.exit_code == 0
        assert result.output.splitlines() == ["https://a/1", "https://a/2"]

    def test_url_target_registers_and_echoes(self, runner, data_dir, monkeypatch):
        seen = {}

        def fake_register(db, urls):
            seen["urls"] = urls
            return urls

        monkeypatch.setattr(cli_module, "register_urls", fake_register)
        monkeypatch.setattr(
            cli_module,
            "index_source",
            lambda *a, **k: pytest.fail("URL must not hit index_source"),
        )
        result = runner.invoke(cli_module.cli, ["index", "https://x.com/1"])
        assert result.exit_code == 0
        assert seen["urls"] == ["https://x.com/1"]
        assert result.output.splitlines() == ["https://x.com/1"]

    def test_all_echoes_indexed_urls(self, runner, data_dir, monkeypatch):
        monkeypatch.setattr(cli_module, "index_all", lambda db: ["https://a/1"])
        result = runner.invoke(cli_module.cli, ["index", "--all"])
        assert result.exit_code == 0
        assert result.output.splitlines() == ["https://a/1"]

    def test_target_and_all_together_errors(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["index", "notes", "--all"])
        assert result.exit_code != 0

    def test_unknown_source_reports_error(self, runner, data_dir, monkeypatch):
        def raise_missing(db, name):
            raise KeyError(f"No source named '{name}'")

        monkeypatch.setattr(cli_module, "index_source", raise_missing)
        result = runner.invoke(cli_module.cli, ["index", "ghost"])
        assert result.exit_code != 0
        assert "No source named 'ghost'" in result.output


class TestFetchCli:
    def test_url_argument_fetches_only_that_url(self, runner, data_dir, monkeypatch):
        calls = {}

        def fake_fetch_urls(db, urls, refetch=False):
            calls["urls"] = urls
            calls["refetch"] = refetch
            return []

        monkeypatch.setattr(cli_module, "fetch_urls", fake_fetch_urls)
        monkeypatch.setattr(
            cli_module,
            "fetch_pending",
            lambda *a, **k: pytest.fail("a URL must not fetch pending"),
        )
        monkeypatch.setattr(cli_module, "report", lambda db, n: None)
        result = runner.invoke(
            cli_module.cli, ["fetch", "https://x.com/1", "--refetch"]
        )
        assert result.exit_code == 0
        assert calls == {"urls": ["https://x.com/1"], "refetch": True}

    def test_no_argument_fetches_pending(self, runner, data_dir, monkeypatch):
        called = {"pending": False}

        def fake_pending(db, refetch=False):
            called["pending"] = True
            return []

        monkeypatch.setattr(cli_module, "fetch_pending", fake_pending)
        monkeypatch.setattr(
            cli_module,
            "fetch_urls",
            lambda *a, **k: pytest.fail("no URL must not fetch a single url"),
        )
        monkeypatch.setattr(cli_module, "report", lambda db, n: None)
        result = runner.invoke(cli_module.cli, ["fetch"])
        assert result.exit_code == 0
        assert called["pending"]


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
