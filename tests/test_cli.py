"""UX-invariant tests for the CLI: stdout/stderr split, exit codes, next-step errors."""

import json
from pathlib import Path

import httpx
import numpy as np
import pytest

from microrag.cli import EX_NOINPUT, EX_OK, EX_UNAVAILABLE, EX_USAGE, main
from microrag.indexer import index_directory


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
def empty_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run with an isolated MICRORAG_HOME: no model, no index."""
    monkeypatch.chdir(tmp_path)
    home = tmp_path / "microrag-home"
    monkeypatch.setattr("microrag.cli.MODEL_DIR", home / "model")
    monkeypatch.setattr("microrag.cli.DEFAULT_DB_DIR", home / "db")
    return tmp_path


def test_no_args_shows_help(empty_cwd: Path, capsys: pytest.CaptureFixture) -> None:
    assert main([]) == EX_OK
    assert "usage: microrag" in capsys.readouterr().out


def test_version_flag(capsys: pytest.CaptureFixture) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert "microrag" in capsys.readouterr().out


def test_index_missing_path(empty_cwd: Path, capsys: pytest.CaptureFixture) -> None:
    code = main(["index", str(empty_cwd / "nope")])
    captured = capsys.readouterr()
    assert code == EX_NOINPUT
    assert captured.out == ""
    assert "Path does not exist" in captured.err


def test_index_without_model_names_next_step(
    empty_cwd: Path, capsys: pytest.CaptureFixture
) -> None:
    notes = empty_cwd / "notes"
    notes.mkdir()
    code = main(["index", str(notes)])
    captured = capsys.readouterr()
    assert code == EX_NOINPUT
    assert captured.out == ""
    assert "microrag download" in captured.err


def test_query_without_index_names_next_step(
    empty_cwd: Path, capsys: pytest.CaptureFixture
) -> None:
    code = main(["query", "anything"])
    captured = capsys.readouterr()
    assert code == EX_NOINPUT
    assert captured.out == ""
    assert "microrag index" in captured.err


def test_query_dash_with_tty_stdin_is_usage_error(
    empty_cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    import io

    class _TtyIn(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr("sys.stdin", _TtyIn())
    code = main(["query", "-"])
    captured = capsys.readouterr()
    assert code == EX_USAGE
    assert captured.out == ""
    assert "microrag query -" in captured.err  # error shows an example pipe


def test_query_dash_reads_stdin(
    empty_cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("some piped query"))
    # No index exists, so it proceeds past stdin handling to the missing-index error.
    code = main(["query", "-"])
    captured = capsys.readouterr()
    assert code == EX_NOINPUT
    assert "microrag index" in captured.err


def test_status_plain_output_is_tab_separated(
    empty_cwd: Path, capsys: pytest.CaptureFixture
) -> None:
    assert main(["status"]) == EX_OK
    out = capsys.readouterr().out
    assert "model_present\tfalse" in out
    assert "chunks\t0" in out


def test_status_json_output(empty_cwd: Path, capsys: pytest.CaptureFixture) -> None:
    assert main(["status", "--json"]) == EX_OK
    obj = json.loads(capsys.readouterr().out)
    assert obj["model_present"] is False
    assert obj["chunks"] == 0


def test_global_flags_work_before_and_after_subcommand(
    empty_cwd: Path, capsys: pytest.CaptureFixture
) -> None:
    assert main(["--json", "status"]) == EX_OK
    json.loads(capsys.readouterr().out)
    assert main(["status", "-q"]) == EX_OK
    capsys.readouterr()


def test_download_network_failure_is_clean(
    empty_cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    def _fail(**_kwargs) -> str:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("microrag.cli.hf_hub_download", _fail)
    code = main(["download"])
    captured = capsys.readouterr()
    assert code == EX_UNAVAILABLE
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert "microrag download" in captured.err


def test_microrag_home_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    import microrag.constants as constants

    try:
        monkeypatch.setenv("MICRORAG_HOME", "/custom/home")
        importlib.reload(constants)
        assert constants.MODEL_DIR == Path("/custom/home/model")
        assert constants.DEFAULT_DB_DIR == Path("/custom/home/db")
    finally:
        monkeypatch.delenv("MICRORAG_HOME")
        importlib.reload(constants)


@pytest.fixture
def fake_embedder(monkeypatch: pytest.MonkeyPatch) -> _FakeEmbedder:
    """Bypass the model download by loading a fake embedder in the CLI."""
    embedder = _FakeEmbedder()
    monkeypatch.setattr("microrag.cli._load_embedder", lambda: embedder)
    return embedder


def test_index_refuses_a_second_root(
    empty_cwd: Path, fake_embedder: _FakeEmbedder, capsys: pytest.CaptureFixture
) -> None:
    first = empty_cwd / "first"
    first.mkdir()
    (first / "a.md").write_text("# A\n\nalpha\n", encoding="utf-8")
    second = empty_cwd / "second"
    second.mkdir()
    (second / "a.md").write_text("# A\n\ncollides\n", encoding="utf-8")

    assert main(["index", str(first)]) == EX_OK
    capsys.readouterr()

    code = main(["index", str(second)])
    captured = capsys.readouterr()
    assert code == EX_USAGE
    assert captured.out == ""
    assert str(first.resolve()) in captured.err
    assert "--collection" in captured.err

    # Re-indexing the recorded root still works.
    assert main(["index", str(first)]) == EX_OK


def test_index_does_not_pin_root_on_empty_walk(
    empty_cwd: Path, fake_embedder: _FakeEmbedder, capsys: pytest.CaptureFixture
) -> None:
    empty = empty_cwd / "empty"
    empty.mkdir()
    notes = empty_cwd / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("# A\n\nalpha\n", encoding="utf-8")

    assert main(["index", str(empty)]) == EX_OK  # a mistyped path must not pin
    assert main(["index", str(notes)]) == EX_OK
    capsys.readouterr()


def test_status_reports_collections_and_roots(
    empty_cwd: Path, fake_embedder: _FakeEmbedder, capsys: pytest.CaptureFixture
) -> None:
    assert main(["status", "--json"]) == EX_OK
    assert json.loads(capsys.readouterr().out)["collections"] == []

    notes = empty_cwd / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("# A\n\nalpha\n", encoding="utf-8")
    assert main(["index", str(notes)]) == EX_OK
    capsys.readouterr()

    assert main(["status", "--json"]) == EX_OK
    obj = json.loads(capsys.readouterr().out)
    assert [c["name"] for c in obj["collections"]] == ["microrag"]
    assert obj["collections"][0]["root"] == str(notes.resolve())
    assert obj["collections"][0]["chunks"] == obj["chunks"] > 0


def test_two_roots_index_into_separate_collections(
    empty_cwd: Path, fake_embedder: _FakeEmbedder, capsys: pytest.CaptureFixture
) -> None:
    notes = empty_cwd / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("# A\n\nalpha notes\n", encoding="utf-8")
    blog = empty_cwd / "blog"
    blog.mkdir()
    (blog / "a.md").write_text("# A\n\nblog post\n", encoding="utf-8")

    assert main(["index", str(notes)]) == EX_OK
    assert main(["index", str(blog), "--collection", "blog"]) == EX_OK
    capsys.readouterr()

    # Default query searches all collections and emits absolute paths.
    assert main(["query", "anything"]) == EX_OK
    lines = capsys.readouterr().out.splitlines()
    assert set(lines) == {str(notes.resolve() / "a.md"), str(blog.resolve() / "a.md")}

    # --collection narrows the search.
    assert main(["query", "anything", "--collection", "blog"]) == EX_OK
    assert capsys.readouterr().out.splitlines() == [str(blog.resolve() / "a.md")]

    # JSON results carry the collection and the absolute path.
    assert main(["query", "anything", "--collection", "blog", "--json"]) == EX_OK
    result = json.loads(capsys.readouterr().out.splitlines()[0])
    assert result["collection"] == "blog"
    assert result["path"] == str(blog.resolve() / "a.md")


def test_query_unknown_collection_is_usage_error(
    empty_cwd: Path, fake_embedder: _FakeEmbedder, capsys: pytest.CaptureFixture
) -> None:
    notes = empty_cwd / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("# A\n\nalpha\n", encoding="utf-8")
    assert main(["index", str(notes)]) == EX_OK
    capsys.readouterr()

    code = main(["query", "anything", "--collection", "nope"])
    captured = capsys.readouterr()
    assert code == EX_USAGE
    assert captured.out == ""
    assert "microrag" in captured.err  # lists the known collections


def test_index_rejects_invalid_collection_name(
    empty_cwd: Path, capsys: pytest.CaptureFixture
) -> None:
    notes = empty_cwd / "notes"
    notes.mkdir()
    code = main(["index", str(notes), "--collection", "a"])
    captured = capsys.readouterr()
    assert code == EX_USAGE
    assert captured.out == ""


def test_legacy_root_marker_still_pins_the_default_collection(
    empty_cwd: Path, fake_embedder: _FakeEmbedder, capsys: pytest.CaptureFixture
) -> None:
    notes = empty_cwd / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("# A\n\nalpha\n", encoding="utf-8")
    other = empty_cwd / "other"
    other.mkdir()
    (other / "a.md").write_text("# A\n\nbeta\n", encoding="utf-8")

    assert main(["index", str(notes)]) == EX_OK
    capsys.readouterr()

    # Rewind the marker to the pre-collections format.
    db = empty_cwd / "microrag-home" / "db"
    (db / "roots.json").unlink()
    (db / "root.txt").write_text(f"{notes.resolve()}\n", encoding="utf-8")

    assert main(["index", str(other)]) == EX_USAGE  # legacy root still pins
    assert main(["index", str(notes)]) == EX_OK
    capsys.readouterr()


def test_index_directory_keeps_stdout_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    (tmp_path / "a.md").write_text("# Title\n\nhello world\n", encoding="utf-8")
    files, chunks, pruned = index_directory(tmp_path, _FakeEmbedder(), _FakeStore())
    assert (files, chunks, pruned) == (1, 1, 0)
    assert capsys.readouterr().out == ""
