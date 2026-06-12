"""Tests for the inspection/data-dir CLI commands (list, cat, status, db)."""

import pytest
from click.testing import CliRunner

import clotho.scripts.cli as cli_module
from clotho.db import Page, PageDatabase


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Point the CLI at a temp data dir and silence the logger setup."""
    monkeypatch.setattr(cli_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cli_module, "DB_PATH", tmp_path / "clotho.db")
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
    with PageDatabase(data_dir / "clotho.db") as db:
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


class TestCat:
    def _seed_parsed(self, data_dir, content: str = "# Hello\n\nArchived text.\n"):
        page = _page(
            "https://example.com/post",
            parsed_at="2026-06-11T01:00:00+00:00",
        )
        _seed(data_dir, [page])
        md_path = data_dir / "saved" / page.slug / "page.md"
        md_path.parent.mkdir(parents=True)
        md_path.write_text(content, encoding="utf-8")
        return content

    def test_prints_archived_markdown(self, runner, data_dir):
        content = self._seed_parsed(data_dir)
        result = runner.invoke(cli_module.cli, ["cat", "https://example.com/post"])
        assert result.exit_code == 0
        assert result.output == content

    def test_url_is_normalized_for_lookup(self, runner, data_dir):
        # Fragments are stripped at index time; cat must match that
        content = self._seed_parsed(data_dir)
        result = runner.invoke(
            cli_module.cli, ["cat", "https://example.com/post#section-2"]
        )
        assert result.exit_code == 0
        assert result.output == content

    def test_unknown_url_fails(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["cat", "https://example.com/nope"])
        assert result.exit_code != 0
        assert "Unknown URL" in result.output

    def test_pending_url_fails_with_hint(self, runner, data_dir):
        _seed(data_dir, [_page("https://example.com/post", fetched_at=None)])
        result = runner.invoke(cli_module.cli, ["cat", "https://example.com/post"])
        assert result.exit_code != 0
        assert "clotho fetch" in result.output

    def test_unparsed_url_fails_with_hint(self, runner, data_dir):
        _seed(data_dir, [_page("https://example.com/post")])
        result = runner.invoke(cli_module.cli, ["cat", "https://example.com/post"])
        assert result.exit_code != 0
        assert "clotho parse" in result.output

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
        result = runner.invoke(cli_module.cli, ["cat", "https://example.com/post"])
        assert result.exit_code != 0
        assert "timeout" in result.output


class TestStatus:
    def test_counts_without_recent_fetches(self, runner, data_dir):
        _seed(data_dir, [_page("https://example.com/a")])
        result = runner.invoke(cli_module.cli, ["status"])
        assert result.exit_code == 0
        assert "Pages: 1 total" in result.output
        # Recently fetched pages moved to `clotho list`
        assert "Recent fetches" not in result.output


class TestDbGroup:
    def test_dir_prints_data_dir(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["db", "dir"])
        assert result.exit_code == 0
        assert result.output.strip() == str(data_dir)

    def test_remove_force_deletes_db_and_sidecars(self, runner, data_dir):
        _seed(data_dir, [_page("https://example.com/a")])
        for suffix in ("-wal", "-shm"):
            (data_dir / f"clotho.db{suffix}").touch()
        result = runner.invoke(cli_module.cli, ["db", "remove", "--force"])
        assert result.exit_code == 0
        assert not (data_dir / "clotho.db").exists()
        assert not (data_dir / "clotho.db-wal").exists()
        assert not (data_dir / "clotho.db-shm").exists()

    def test_remove_asks_and_aborts_on_no(self, runner, data_dir):
        _seed(data_dir, [_page("https://example.com/a")])
        result = runner.invoke(cli_module.cli, ["db", "remove"], input="n\n")
        assert result.exit_code != 0
        assert (data_dir / "clotho.db").exists()

    def test_remove_asks_and_deletes_on_yes(self, runner, data_dir):
        _seed(data_dir, [_page("https://example.com/a")])
        result = runner.invoke(cli_module.cli, ["db", "remove"], input="y\n")
        assert result.exit_code == 0
        assert not (data_dir / "clotho.db").exists()

    def test_remove_without_db_is_graceful(self, runner, data_dir):
        result = runner.invoke(cli_module.cli, ["db", "remove"])
        assert result.exit_code == 0
        assert "No database" in result.output
