"""UX-invariant tests for `arciv search`: stdout/stderr split, exit codes, next steps.

Driven through the real ``arciv`` CLI with CliRunner, so these also cover that
the search sub-app inherits Arciv's global flags (the parent callback sets
--json/-v, which the commands read) regardless of flag position.
"""

import json
import sys
from pathlib import Path

import httpx
import numpy as np
import pytest
from loguru import logger
from typer.testing import CliRunner

import arciv.cli.cli as cli_module
import arciv.cli.search as search_module
from arciv.cli import output
from arciv.cli.output import (
    EXIT_DATAERR,
    EXIT_NOINPUT,
    EXIT_OK,
    EXIT_UNAVAILABLE,
    EXIT_USAGE,
)
from arciv.search.indexer import index_directory


class _FakeEmbedder:
    def embed_documents(self, texts: list[str]) -> np.ndarray:
        vectors = np.zeros((len(texts), 4), dtype=np.float32)
        vectors[:, 0] = 1.0  # unit norm keeps cosine distances well-defined
        return vectors

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_documents([text])


class _FakeStore:
    def upsert(self, ids, embeddings, documents, metadatas) -> None:
        pass

    def ids_by_source(self) -> dict[str, list[str]]:
        return {}

    def delete(self, ids: list[str]) -> None:
        pass


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def search_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated search home (no model, no index) with a deterministic logger.

    Points the search command module at a temp home and reconfigures loguru to
    a synchronous message-only stderr sink, so stdout/stderr assertions are
    stable. The global --json/-v state is reset around each test.
    """
    monkeypatch.chdir(tmp_path)
    home = tmp_path / "search-home"
    monkeypatch.setattr(search_module, "MODEL_DIR", home / "model")
    monkeypatch.setattr(search_module, "DEFAULT_DB_DIR", home / "db")

    def fake_configure(
        level: str = "INFO", color: str = "auto", log_file: bool = False
    ) -> None:
        logger.remove()
        logger.add(sys.stderr, level=level, format="{message}", enqueue=False)

    monkeypatch.setattr(cli_module, "configure_logger", fake_configure)
    output.set_json_output(False)
    output.set_verbosity(0)
    yield tmp_path
    logger.remove()
    output.set_json_output(False)
    output.set_verbosity(0)


@pytest.fixture
def fake_embedder(monkeypatch: pytest.MonkeyPatch) -> _FakeEmbedder:
    """Bypass the model download by loading a fake embedder in the CLI."""
    embedder = _FakeEmbedder()
    monkeypatch.setattr(search_module, "_load_embedder", lambda: embedder)
    return embedder


def _search(runner: CliRunner, *args: str, **kwargs):
    """Invoke ``arciv search <args...>`` and return the result."""
    return runner.invoke(cli_module.cli, ["search", *args], **kwargs)


def test_help_lists_commands(runner: CliRunner, search_env: Path) -> None:
    result = _search(runner, "--help")
    assert result.exit_code == EXIT_OK
    assert "query" in result.output  # help lists the commands
    assert "index" in result.output


def test_index_missing_path(runner: CliRunner, search_env: Path) -> None:
    result = _search(runner, "index", str(search_env / "nope"))
    assert result.exit_code == EXIT_NOINPUT
    assert result.stdout == ""
    assert "Path does not exist" in result.stderr


def test_index_without_model_names_next_step(
    runner: CliRunner, search_env: Path
) -> None:
    notes = search_env / "notes"
    notes.mkdir()
    result = _search(runner, "index", str(notes))
    assert result.exit_code == EXIT_NOINPUT
    assert result.stdout == ""
    assert "arciv search download" in result.stderr


def test_query_without_index_names_next_step(
    runner: CliRunner, search_env: Path
) -> None:
    result = _search(runner, "query", "anything")
    assert result.exit_code == EXIT_NOINPUT
    assert result.stdout == ""
    assert "arciv search index" in result.stderr


def test_query_dash_empty_stdin_is_usage_error(
    runner: CliRunner, search_env: Path
) -> None:
    # "-" reads stdin; empty input is a clean usage error, not a crash.
    result = _search(runner, "query", "-", input="")
    assert result.exit_code == EXIT_USAGE
    assert result.stdout == ""
    assert "Empty query text on stdin" in result.stderr


def test_query_dash_reads_stdin(runner: CliRunner, search_env: Path) -> None:
    # No index exists, so it proceeds past stdin handling to the missing-index error.
    result = _search(runner, "query", "-", input="some piped query")
    assert result.exit_code == EXIT_NOINPUT
    assert "arciv search index" in result.stderr


def test_status_plain_output_is_tab_separated(
    runner: CliRunner, search_env: Path
) -> None:
    result = _search(runner, "status")
    assert result.exit_code == EXIT_OK
    assert "model_present\tfalse" in result.stdout
    assert "collections_count\t0" in result.stdout
    assert "chunks\t0" in result.stdout


def test_status_json_output(runner: CliRunner, search_env: Path) -> None:
    result = _search(runner, "status", "--json")
    assert result.exit_code == EXIT_OK
    obj = json.loads(result.stdout)
    assert obj["model_present"] is False
    assert obj["chunks"] == 0
    assert obj["collections_count"] == 0


def test_global_flags_work_before_and_after_subcommand(
    runner: CliRunner, search_env: Path
) -> None:
    # --json is a parent-callback flag; it must reach the search command
    # whether written before or after "search status".
    before = runner.invoke(cli_module.cli, ["--json", "search", "status"])
    assert before.exit_code == EXIT_OK
    json.loads(before.stdout)
    after = _search(runner, "status", "--json")
    assert after.exit_code == EXIT_OK
    json.loads(after.stdout)


def test_verbose_logs_never_reach_stdout(runner: CliRunner, search_env: Path) -> None:
    # stdout is data only: even at -v, diagnostics stay on stderr.
    result = _search(runner, "status", "-v")
    assert result.exit_code == EXIT_OK
    assert "DEBUG" not in result.stdout
    assert "WARNING" not in result.stdout  # "model not downloaded" hint is stderr
    assert result.stdout.startswith("model_dir\t")


def test_download_network_failure_is_clean(
    runner: CliRunner, search_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail(**_kwargs) -> str:
        raise httpx.ConnectError("connection refused")

    # download() imports hf_hub_download from huggingface_hub at call time, so
    # patch it on the source module.
    monkeypatch.setattr("huggingface_hub.hf_hub_download", _fail)
    result = _search(runner, "download")
    assert result.exit_code == EXIT_UNAVAILABLE
    assert result.stdout == ""
    assert "Traceback" not in result.stderr
    assert "arciv search download" in result.stderr


def test_index_refuses_a_second_root(
    runner: CliRunner, search_env: Path, fake_embedder: _FakeEmbedder
) -> None:
    first = search_env / "first"
    first.mkdir()
    (first / "a.md").write_text("# A\n\nalpha\n", encoding="utf-8")
    second = search_env / "second"
    second.mkdir()
    (second / "a.md").write_text("# A\n\ncollides\n", encoding="utf-8")

    assert _search(runner, "index", str(first)).exit_code == EXIT_OK

    result = _search(runner, "index", str(second))
    assert result.exit_code == EXIT_USAGE
    assert result.stdout == ""
    assert str(first.resolve()) in result.stderr
    assert "--collection" in result.stderr

    # Re-indexing the recorded root still works.
    assert _search(runner, "index", str(first)).exit_code == EXIT_OK


def test_index_does_not_pin_root_on_empty_walk(
    runner: CliRunner, search_env: Path, fake_embedder: _FakeEmbedder
) -> None:
    empty = search_env / "empty"
    empty.mkdir()
    notes = search_env / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("# A\n\nalpha\n", encoding="utf-8")

    assert _search(runner, "index", str(empty)).exit_code == EXIT_OK  # must not pin
    assert _search(runner, "index", str(notes)).exit_code == EXIT_OK


def test_status_reports_collections_and_roots(
    runner: CliRunner, search_env: Path, fake_embedder: _FakeEmbedder
) -> None:
    empty = _search(runner, "status", "--json")
    assert empty.exit_code == EXIT_OK
    assert json.loads(empty.stdout)["collections"] == []

    notes = search_env / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("# A\n\nalpha\n", encoding="utf-8")
    assert _search(runner, "index", str(notes)).exit_code == EXIT_OK

    result = _search(runner, "status", "--json")
    assert result.exit_code == EXIT_OK
    obj = json.loads(result.stdout)
    assert [c["name"] for c in obj["collections"]] == ["microrag"]
    assert obj["collections"][0]["root"] == str(notes.resolve())
    assert obj["collections"][0]["chunks"] == obj["chunks"] > 0
    assert obj["collections_count"] == 1


def test_collections_command_lists_name_path_files_chunks(
    runner: CliRunner, search_env: Path, fake_embedder: _FakeEmbedder
) -> None:
    # No index yet: an empty listing, and a next-step hint on stderr.
    empty = _search(runner, "collections", "--json")
    assert empty.exit_code == EXIT_OK
    assert empty.stdout == ""

    notes = search_env / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("# A\n\nalpha\n", encoding="utf-8")
    (notes / "b.md").write_text("# B\n\nbeta\n", encoding="utf-8")
    assert _search(runner, "index", str(notes)).exit_code == EXIT_OK

    # JSON: one record per collection with name, path, files, chunks.
    result = _search(runner, "collections", "--json")
    assert result.exit_code == EXIT_OK
    record = json.loads(result.stdout.splitlines()[0])
    assert record["name"] == "microrag"
    assert record["path"] == str(notes.resolve())
    assert record["files"] == 2
    assert record["chunks"] > 0

    # Plain: tab-separated name, path, files, chunks.
    plain = _search(runner, "collections")
    assert plain.exit_code == EXIT_OK
    fields = plain.stdout.splitlines()[0].split("\t")
    assert fields[0] == "microrag"
    assert fields[1] == str(notes.resolve())
    assert fields[2] == "2"


def test_two_roots_index_into_separate_collections(
    runner: CliRunner, search_env: Path, fake_embedder: _FakeEmbedder
) -> None:
    notes = search_env / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("# A\n\nalpha notes\n", encoding="utf-8")
    blog = search_env / "blog"
    blog.mkdir()
    (blog / "a.md").write_text("# A\n\nblog post\n", encoding="utf-8")

    assert _search(runner, "index", str(notes)).exit_code == EXIT_OK
    assert (
        _search(runner, "index", str(blog), "--collection", "blog").exit_code == EXIT_OK
    )

    # Default query searches all collections and emits absolute paths.
    everything = _search(runner, "query", "anything")
    assert everything.exit_code == EXIT_OK
    assert set(everything.stdout.splitlines()) == {
        str(notes.resolve() / "a.md"),
        str(blog.resolve() / "a.md"),
    }

    # --collection narrows the search.
    narrowed = _search(runner, "query", "anything", "--collection", "blog")
    assert narrowed.stdout.splitlines() == [str(blog.resolve() / "a.md")]

    # -0/--null emits NUL-separated paths (find -print0 style) for xargs -0.
    nulled = _search(runner, "query", "anything", "-0")
    assert "\n" not in nulled.stdout
    assert set(nulled.stdout.split("\0")) == {
        str(notes.resolve() / "a.md"),
        str(blog.resolve() / "a.md"),
        "",  # trailing NUL after the last record
    }

    # JSON results carry the collection and the absolute path.
    as_json = _search(runner, "query", "anything", "--collection", "blog", "--json")
    result = json.loads(as_json.stdout.splitlines()[0])
    assert result["collection"] == "blog"
    assert result["path"] == str(blog.resolve() / "a.md")


def test_query_verbose_locates_the_hit_and_drops_the_breadcrumb(
    runner: CliRunner, search_env: Path, fake_embedder: _FakeEmbedder
) -> None:
    notes = search_env / "notes"
    notes.mkdir()
    (notes / "doc.md").write_text("# Heading\n\nbodytext\n", encoding="utf-8")
    assert _search(runner, "index", str(notes)).exit_code == EXIT_OK

    result = _search(runner, "query", "anything", "-v")
    assert result.exit_code == EXIT_OK
    out = result.stdout
    # The hit is located as path:line, so it can be opened where it starts.
    assert f"path={notes.resolve() / 'doc.md'}:3" in out
    # The breadcrumb is context for the embedder, not output: the chunker
    # prepends it to the chunk text, so the body must not repeat it.
    assert "  | doc > Heading" not in out
    assert "  | bodytext" in out


def test_query_json_carries_the_line(
    runner: CliRunner, search_env: Path, fake_embedder: _FakeEmbedder
) -> None:
    notes = search_env / "notes"
    notes.mkdir()
    (notes / "doc.md").write_text(
        "# Heading\n\nintro\n\n## Later\n\nbodytext\n", encoding="utf-8"
    )
    assert _search(runner, "index", str(notes)).exit_code == EXIT_OK

    result = _search(runner, "query", "anything", "--json", "-k", "2")
    assert result.exit_code == EXIT_OK
    records = [json.loads(line) for line in result.stdout.splitlines()]
    assert {record["line"] for record in records} == {3, 7}


def test_query_verbose_tolerates_an_index_without_lines(
    runner: CliRunner, search_env: Path, fake_embedder: _FakeEmbedder
) -> None:
    """Indexes written before line metadata existed still print their path."""
    notes = search_env / "notes"
    notes.mkdir()
    (notes / "doc.md").write_text("# Heading\n\nbodytext\n", encoding="utf-8")
    assert _search(runner, "index", str(notes)).exit_code == EXIT_OK

    # Replace the indexed chunks with a row that carries no line metadata.
    from arciv.search.store import Store

    store = Store(search_env / "search-home" / "db", "microrag")
    store.delete([cid for cids in store.ids_by_source().values() for cid in cids])
    document = "doc > Heading\n\nbodytext"
    store.upsert(
        ids=["legacy"],
        embeddings=fake_embedder.embed_documents([document]),
        documents=[document],
        metadatas=[{"source": "doc.md", "heading": "doc > Heading", "index": 0}],
    )

    result = _search(runner, "query", "anything", "-v")
    assert result.exit_code == EXIT_OK
    assert f"path={notes.resolve() / 'doc.md'}\n" in result.stdout


def test_query_rejects_non_positive_limit(
    runner: CliRunner, search_env: Path, fake_embedder: _FakeEmbedder
) -> None:
    notes = search_env / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("# A\n\nalpha\n", encoding="utf-8")
    assert _search(runner, "index", str(notes)).exit_code == EXIT_OK

    for limit in ("0", "-3"):
        result = _search(runner, "query", "anything", "-k", limit)
        assert result.exit_code == EXIT_USAGE
        assert result.stdout == ""
        assert "--limit" in result.stderr


def test_corrupted_roots_marker_fails_cleanly(
    runner: CliRunner, search_env: Path, fake_embedder: _FakeEmbedder
) -> None:
    notes = search_env / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("# A\n\nalpha\n", encoding="utf-8")
    assert _search(runner, "index", str(notes)).exit_code == EXIT_OK

    db = search_env / "search-home" / "db"
    (db / "roots.json").write_text('{"microrag": "truncated', encoding="utf-8")

    result = _search(runner, "status")
    assert result.exit_code == EXIT_DATAERR
    assert "roots.json" in result.stderr  # names the file to fix or delete


def test_query_unknown_collection_is_usage_error(
    runner: CliRunner, search_env: Path, fake_embedder: _FakeEmbedder
) -> None:
    notes = search_env / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("# A\n\nalpha\n", encoding="utf-8")
    assert _search(runner, "index", str(notes)).exit_code == EXIT_OK

    result = _search(runner, "query", "anything", "--collection", "nope")
    assert result.exit_code == EXIT_USAGE
    assert result.stdout == ""
    assert "microrag" in result.stderr  # lists the known collections


def test_index_rejects_invalid_collection_name(
    runner: CliRunner, search_env: Path
) -> None:
    notes = search_env / "notes"
    notes.mkdir()
    result = _search(runner, "index", str(notes), "--collection", "a")
    assert result.exit_code == EXIT_USAGE
    assert result.stdout == ""


def test_legacy_root_marker_still_pins_the_default_collection(
    runner: CliRunner, search_env: Path, fake_embedder: _FakeEmbedder
) -> None:
    notes = search_env / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("# A\n\nalpha\n", encoding="utf-8")
    other = search_env / "other"
    other.mkdir()
    (other / "a.md").write_text("# A\n\nbeta\n", encoding="utf-8")

    assert _search(runner, "index", str(notes)).exit_code == EXIT_OK

    # Rewind the marker to the pre-collections format.
    db = search_env / "search-home" / "db"
    (db / "roots.json").unlink()
    (db / "root.txt").write_text(f"{notes.resolve()}\n", encoding="utf-8")

    assert _search(runner, "index", str(other)).exit_code == EXIT_USAGE  # legacy pins
    assert _search(runner, "index", str(notes)).exit_code == EXIT_OK


def test_refresh_ingests_new_files_from_recorded_root(
    runner: CliRunner, search_env: Path, fake_embedder: _FakeEmbedder
) -> None:
    # Refresh re-walks the recorded root, so a file added after indexing gets
    # picked up without retyping the path.
    notes = search_env / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("# A\n\nalpha\n", encoding="utf-8")
    assert _search(runner, "index", str(notes)).exit_code == EXIT_OK

    (notes / "b.md").write_text("# B\n\nbeta\n", encoding="utf-8")
    refreshed = _search(runner, "refresh")
    assert refreshed.exit_code == EXIT_OK
    assert refreshed.stdout == ""  # plain mode keeps stdout clean

    result = _search(runner, "collections", "--json")
    record = json.loads(result.stdout.splitlines()[0])
    assert record["files"] == 2


def test_refresh_specific_collection_leaves_others_untouched(
    runner: CliRunner, search_env: Path, fake_embedder: _FakeEmbedder
) -> None:
    notes = search_env / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("# A\n\nalpha\n", encoding="utf-8")
    blog = search_env / "blog"
    blog.mkdir()
    (blog / "a.md").write_text("# A\n\nblog\n", encoding="utf-8")
    assert _search(runner, "index", str(notes)).exit_code == EXIT_OK
    assert (
        _search(runner, "index", str(blog), "--collection", "blog").exit_code == EXIT_OK
    )

    # Add a file to each root, then refresh only blog.
    (notes / "b.md").write_text("# B\n\nbeta\n", encoding="utf-8")
    (blog / "b.md").write_text("# B\n\nblog two\n", encoding="utf-8")
    assert _search(runner, "refresh", "--collection", "blog").exit_code == EXIT_OK

    result = _search(runner, "collections", "--json")
    by_name = {r["name"]: r for r in map(json.loads, result.stdout.splitlines())}
    assert by_name["blog"]["files"] == 2  # refreshed
    assert by_name["microrag"]["files"] == 1  # untouched


def test_refresh_without_index_names_next_step(
    runner: CliRunner, search_env: Path
) -> None:
    result = _search(runner, "refresh")
    assert result.exit_code == EXIT_NOINPUT
    assert result.stdout == ""
    assert "arciv search index" in result.stderr


def test_refresh_unknown_collection_is_usage_error(
    runner: CliRunner, search_env: Path, fake_embedder: _FakeEmbedder
) -> None:
    notes = search_env / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("# A\n\nalpha\n", encoding="utf-8")
    assert _search(runner, "index", str(notes)).exit_code == EXIT_OK

    result = _search(runner, "refresh", "--collection", "nope")
    assert result.exit_code == EXIT_USAGE
    assert result.stdout == ""
    assert "microrag" in result.stderr  # lists the known collections


def test_refresh_skips_collection_whose_root_is_gone(
    runner: CliRunner, search_env: Path, fake_embedder: _FakeEmbedder
) -> None:
    notes = search_env / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("# A\n\nalpha\n", encoding="utf-8")
    assert _search(runner, "index", str(notes)).exit_code == EXIT_OK

    # The recorded root disappears (moved/deleted); refresh must not crash or
    # wipe the collection, just skip it with a clear warning.
    for md in notes.iterdir():
        md.unlink()
    notes.rmdir()
    result = _search(runner, "refresh")
    assert result.exit_code == EXIT_OK
    assert result.stdout == ""
    assert "no longer exists" in result.stderr

    # The data survived the skip.
    survived = _search(runner, "collections", "--json")
    assert json.loads(survived.stdout.splitlines()[0])["chunks"] > 0


def test_refresh_prunes_deleted_files(
    runner: CliRunner, search_env: Path, fake_embedder: _FakeEmbedder
) -> None:
    notes = search_env / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("# A\n\nalpha\n", encoding="utf-8")
    (notes / "b.md").write_text("# B\n\nbeta\n", encoding="utf-8")
    assert _search(runner, "index", str(notes)).exit_code == EXIT_OK

    (notes / "b.md").unlink()
    # --no-prune keeps the orphaned file's chunks.
    kept = _search(runner, "refresh", "--no-prune", "--json")
    record = json.loads(kept.stdout.splitlines()[0])
    assert record["pruned"] == 0
    assert record["files"] == 1

    # A plain refresh prunes them.
    pruned = _search(runner, "refresh", "--json")
    record = json.loads(pruned.stdout.splitlines()[0])
    assert record["pruned"] > 0


def test_index_directory_keeps_stdout_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    (tmp_path / "a.md").write_text("# Title\n\nhello world\n", encoding="utf-8")
    files, chunks, pruned = index_directory(tmp_path, _FakeEmbedder(), _FakeStore())
    assert (files, chunks, pruned) == (1, 1, 0)
    assert capsys.readouterr().out == ""
